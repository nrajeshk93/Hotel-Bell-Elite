package com.hotelbellelite.hbe

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.FileProvider
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Background pull of a newer signed shell APK from production.
 * UI HTML updates come from /mobile-app/ without an APK; this covers native shell bumps.
 */
object AppUpdater {
    private const val TAG = "HbeAppUpdater"
    private const val MANIFEST_URL = "https://belleliteaccounts.com/api/mobile/shell/version"
    private const val MAX_APK_BYTES = 150L * 1024L * 1024L
    private const val APK_NAME = "hbe-shell-update.apk"
    private const val SHA_NAME = "hbe-shell-update.sha256"

    private val busy = AtomicBoolean(false)
    private val hooked = AtomicBoolean(false)
    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val lock = Any()
    private val snapshot = JSONObject()
        .put("state", "idle")
        .put("localVersion", "")
        .put("localCode", 0)
        .put("remoteVersion", "")
        .put("remoteCode", 0)
        .put("message", "")
        .put("apkReady", false)
        .put("canManual", false)

    @Volatile
    private var appRef: Context? = null

    var onStatus: ((String) -> Unit)? = null

    fun attach(context: Context) {
        appRef = context.applicationContext
        fillLocal(context.applicationContext)
        ensureInstallHook()
    }

    fun statusJson(): String {
        synchronized(lock) {
            return snapshot.toString()
        }
    }

    fun checkSoon(context: Context, delayMs: Long = 2_500L) {
        val app = context.applicationContext
        appRef = app
        ensureInstallHook()
        main.postDelayed({ checkNow(app) }, delayMs.coerceAtLeast(0L))
    }

    fun checkNow(context: Context) {
        val app = context.applicationContext
        appRef = app
        ensureInstallHook()
        fillLocal(app)
        if (!busy.compareAndSet(false, true)) {
            // Already checking/installing — keep current status so About can poll it.
            return
        }
        val local = localVer(app)
        publishStatus {
            put("state", "checking")
            put("localVersion", local.name)
            put("localCode", local.code)
            put("message", "Checking…")
        }
        executor.execute {
            try {
                runCheck(app, local)
            } catch (e: Exception) {
                Log.w(TAG, "check failed", e)
                val dest = destFile(app)
                val destOk = dest.isFile && dest.length() > 0
                publishStatus {
                    put("state", "error")
                    put("message", e.message?.takeIf { it.isNotBlank() } ?: "Update check failed")
                    put("apkReady", destOk)
                    put("canManual", destOk)
                }
            } finally {
                busy.set(false)
            }
        }
    }

    fun installDownloaded(context: Context) {
        val app = context.applicationContext
        appRef = app
        ensureInstallHook()
        val dest = destFile(app)
        if (!dest.isFile || dest.length() <= 0) {
            checkNow(app)
            return
        }
        if (!busy.compareAndSet(false, true)) return
        executor.execute {
            try {
                if (!destValid(app, dest)) {
                    dest.delete()
                    shaFile(app).delete()
                    publishStatus {
                        put("state", "error")
                        put("message", "Downloaded APK is not valid")
                        put("apkReady", false)
                        put("canManual", false)
                    }
                    return@execute
                }
                publishStatus {
                    put("state", "installing")
                    put("message", "Installing…")
                    put("apkReady", true)
                    put("canManual", true)
                }
                applyInstallResult(app, SilentUpdateHelper.installApk(app, dest.absolutePath), dest)
            } catch (e: Exception) {
                Log.w(TAG, "installDownloaded failed", e)
                val destOk = dest.isFile && dest.length() > 0
                publishStatus {
                    put("state", "error")
                    put("message", e.message?.takeIf { it.isNotBlank() } ?: "Install failed")
                    put("apkReady", destOk)
                    put("canManual", destOk)
                }
            } finally {
                busy.set(false)
            }
        }
    }

    fun installDownloadedManual(context: Context) {
        val app = context.applicationContext
        appRef = app
        val dest = destFile(app)
        if (!dest.isFile || dest.length() <= 0) {
            publishStatus {
                put("state", "error")
                put("message", "No update downloaded yet")
                put("apkReady", false)
                put("canManual", false)
            }
            return
        }
        if (!destValid(app, dest)) {
            dest.delete()
            shaFile(app).delete()
            publishStatus {
                put("state", "error")
                put("message", "Downloaded APK is not valid")
                put("apkReady", false)
                put("canManual", false)
            }
            return
        }
        main.post {
            try {
                val uri = FileProvider.getUriForFile(
                    app,
                    "${app.packageName}.fileprovider",
                    dest,
                )
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(
                        Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK,
                    )
                }
                app.startActivity(intent)
                publishStatus {
                    put("state", "pending_user_action")
                    put("message", "Confirm the system install sheet")
                    put("apkReady", true)
                    put("canManual", true)
                }
            } catch (e: Exception) {
                Log.e(TAG, "manual install failed", e)
                publishStatus {
                    put("state", "error")
                    put("message", e.message?.takeIf { it.isNotBlank() } ?: "Manual install failed")
                    put("apkReady", true)
                    put("canManual", true)
                }
            }
        }
    }

    private fun runCheck(app: Context, local: LocalVer) {
        val manifest = fetchJson(MANIFEST_URL)
        if (manifest == null) {
            val destOk = destFile(app).isFile && destFile(app).length() > 0
            publishStatus {
                put("state", "error")
                put("localVersion", local.name)
                put("localCode", local.code)
                put("message", "Couldn’t reach the update server")
                put("apkReady", destOk)
                put("canManual", destOk)
            }
            return
        }

        val remoteCode = manifest.optInt("versionCode", 0)
        val remoteVersion = manifest.optString("version", "")
        val apkAvailable = manifest.optBoolean("apk_available", false)
        publishStatus {
            put("localVersion", local.name)
            put("localCode", local.code)
            put("remoteVersion", remoteVersion)
            put("remoteCode", remoteCode)
        }

        if (!apkAvailable || remoteCode <= local.code) {
            val dest = destFile(app)
            if (dest.isFile) dest.delete()
            shaFile(app).delete()
            val msg = if (!apkAvailable) {
                "You’re up to date"
            } else {
                "You’re up to date"
            }
            publishStatus {
                put("state", "up_to_date")
                put("message", msg)
                put("apkReady", false)
                put("canManual", false)
            }
            Log.i(TAG, "up to date local=${local.code} remote=$remoteCode ($remoteVersion) apk=$apkAvailable")
            return
        }

        publishStatus {
            put("state", "update_available")
            put("remoteVersion", remoteVersion)
            put("remoteCode", remoteCode)
            put("message", "Update available $remoteVersion")
            put("apkReady", false)
            put("canManual", false)
        }
        postUpdateNotification(app, remoteCode, remoteVersion)

        val sha256 = manifest.optString("sha256", "").trim().lowercase()
        if (sha256.isEmpty()) {
            publishStatus {
                put("state", "error")
                put("message", "Update manifest is missing a checksum")
                put("apkReady", false)
                put("canManual", false)
            }
            Log.w(TAG, "manifest missing sha256")
            return
        }
        var apkUrl = manifest.optString("apk_url", "/api/mobile/hbe.apk").trim()
        if (apkUrl.startsWith("/")) {
            apkUrl = "https://belleliteaccounts.com$apkUrl"
        }
        if (!apkUrl.startsWith("https://belleliteaccounts.com/")) {
            publishStatus {
                put("state", "error")
                put("message", "Update URL is not allowed")
                put("apkReady", false)
                put("canManual", false)
            }
            Log.e(TAG, "refusing off-host apk url")
            return
        }

        val dest = destFile(app)
        publishStatus {
            put("state", "downloading")
            put("message", "Downloading…")
            put("apkReady", false)
            put("canManual", false)
        }
        Log.i(TAG, "downloading $apkUrl → ${dest.absolutePath}")
        try {
            downloadFile(apkUrl, dest)
        } catch (e: Exception) {
            dest.delete()
            File(dest.absolutePath + ".part").delete()
            shaFile(app).delete()
            publishStatus {
                put("state", "error")
                put("message", e.message?.takeIf { it.isNotBlank() } ?: "Download failed")
                put("apkReady", false)
                put("canManual", false)
            }
            return
        }
        if (!sha256Matches(dest, sha256)) {
            Log.e(TAG, "sha256 mismatch")
            dest.delete()
            shaFile(app).delete()
            publishStatus {
                put("state", "error")
                put("message", "Downloaded APK failed checksum")
                put("apkReady", false)
                put("canManual", false)
            }
            return
        }
        val pkg = SilentUpdateHelper.apkPackageName(app, dest.absolutePath)
        if (pkg != SilentUpdateHelper.EXPECTED_PACKAGE) {
            Log.e(TAG, "package mismatch got=$pkg")
            dest.delete()
            shaFile(app).delete()
            publishStatus {
                put("state", "error")
                put("message", "Downloaded APK is not Hotel Bell Elite")
                put("apkReady", false)
                put("canManual", false)
            }
            return
        }
        shaFile(app).writeText(sha256)
        publishStatus {
            put("state", "installing")
            put("message", "Installing…")
            put("apkReady", true)
            put("canManual", true)
        }
        val result = SilentUpdateHelper.installApk(app, dest.absolutePath)
        Log.i(TAG, "install result=$result")
        applyInstallResult(app, result, dest)
    }

    private fun applyInstallResult(app: Context, result: String, dest: File) {
        val destOk = dest.isFile && dest.length() > 0
        when {
            result == "need_permission" -> publishStatus {
                put("state", "need_permission")
                put("message", "Allow installs from this source, then tap Check again")
                put("apkReady", destOk)
                put("canManual", destOk)
            }
            result == "started" -> publishStatus {
                put("state", "installing")
                put("message", "Installing…")
                put("apkReady", destOk)
                put("canManual", destOk)
            }
            result.startsWith("error") -> publishStatus {
                put("state", "error")
                put("message", result.removePrefix("error:").ifBlank { "Install failed" })
                put("apkReady", destOk)
                put("canManual", destOk)
            }
            else -> publishStatus {
                put("state", "error")
                put("message", result.ifBlank { "Install failed" })
                put("apkReady", destOk)
                put("canManual", destOk)
            }
        }
    }

    private fun postUpdateNotification(app: Context, remoteCode: Int, remoteVersion: String) {
        val items = JSONArray().put(
            JSONObject()
                .put("id", "apk-update-$remoteCode")
                .put("title", "Update available")
                .put("body", "Hotel Bell Elite $remoteVersion is ready to install.")
                .put("screen", "about")
                .put("count", remoteCode),
        )
        main.post {
            try {
                HbeNotifications.showFromJson(app, items)
            } catch (e: Exception) {
                Log.w(TAG, "update notification failed", e)
            }
        }
    }

    private fun ensureInstallHook() {
        if (!hooked.compareAndSet(false, true)) return
        SilentUpdateHelper.setStatusCallback { state, message ->
            val app = appRef
            val destOk = app != null && destFile(app).isFile && destFile(app).length() > 0
            when (state) {
                "pending_user_action" -> publishStatus {
                    put("state", "pending_user_action")
                    put("message", message.ifBlank { "Confirm the system install sheet" })
                    put("apkReady", destOk)
                    put("canManual", destOk)
                }
                "error" -> publishStatus {
                    put("state", "error")
                    put("message", message.ifBlank { "Install failed" })
                    put("apkReady", destOk)
                    put("canManual", destOk)
                }
                else -> {
                    // success / installing: keep installing; app relaunches.
                    publishStatus {
                        put("state", "installing")
                        put("message", message.ifBlank { "Installing…" })
                        put("apkReady", destOk)
                        put("canManual", destOk)
                    }
                }
            }
        }
    }

    private data class LocalVer(val name: String, val code: Int)

    private fun localVer(app: Context): LocalVer {
        return try {
            val info = app.packageManager.getPackageInfo(app.packageName, 0)
            val code = if (android.os.Build.VERSION.SDK_INT >= 28) {
                info.longVersionCode.toInt()
            } else {
                @Suppress("DEPRECATION")
                info.versionCode
            }
            LocalVer(info.versionName ?: BuildConfig.VERSION_NAME, code)
        } catch (e: Exception) {
            Log.w(TAG, "local version lookup failed", e)
            LocalVer(BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)
        }
    }

    private fun fillLocal(app: Context) {
        val local = localVer(app)
        val destOk = destFile(app).isFile && destFile(app).length() > 0
        synchronized(lock) {
            if (snapshot.optString("localVersion").isBlank() || snapshot.optInt("localCode") == 0) {
                snapshot.put("localVersion", local.name)
                snapshot.put("localCode", local.code)
            }
            if (destOk && !snapshot.optBoolean("apkReady")) {
                snapshot.put("apkReady", true)
                snapshot.put("canManual", true)
            }
        }
    }

    private fun destFile(app: Context) = File(app.cacheDir, APK_NAME)

    private fun shaFile(app: Context) = File(app.cacheDir, SHA_NAME)

    private fun destValid(app: Context, dest: File): Boolean {
        if (!dest.isFile || dest.length() <= 0) return false
        val expected = shaFile(app).takeIf { it.isFile }?.readText()?.trim()?.lowercase().orEmpty()
        if (expected.isNotEmpty() && !sha256Matches(dest, expected)) return false
        val pkg = SilentUpdateHelper.apkPackageName(app, dest.absolutePath)
        return pkg == SilentUpdateHelper.EXPECTED_PACKAGE
    }

    private fun publishStatus(mutate: JSONObject.() -> Unit) {
        val json: String
        synchronized(lock) {
            snapshot.mutate()
            json = snapshot.toString()
        }
        Log.i(TAG, "status $json")
        main.post { onStatus?.invoke(json) }
    }

    private fun fetchJson(url: String): JSONObject? {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            requestMethod = "GET"
            setRequestProperty("Cache-Control", "no-cache")
            setRequestProperty("User-Agent", "HBE-Android-Shell-OTA/${BuildConfig.VERSION_NAME}")
        }
        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                Log.w(TAG, "manifest HTTP $code")
                return null
            }
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            return JSONObject(body)
        } finally {
            conn.disconnect()
        }
    }

    private fun downloadFile(url: String, dest: File) {
        val tmp = File(dest.absolutePath + ".part")
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20_000
            readTimeout = 120_000
            instanceFollowRedirects = true
            requestMethod = "GET"
            setRequestProperty("Cache-Control", "no-cache")
            setRequestProperty("User-Agent", "HBE-Android-Shell-OTA/${BuildConfig.VERSION_NAME}")
        }
        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                throw IllegalStateException("apk HTTP $code")
            }
            var written = 0L
            conn.inputStream.use { input ->
                FileOutputStream(tmp).use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        written += n
                        if (written > MAX_APK_BYTES) {
                            throw IllegalStateException("apk too large")
                        }
                        output.write(buf, 0, n)
                    }
                }
            }
            if (!tmp.renameTo(dest)) {
                tmp.copyTo(dest, overwrite = true)
                tmp.delete()
            }
        } finally {
            conn.disconnect()
            if (tmp.exists() && (!dest.isFile || dest.length() <= 0)) {
                tmp.delete()
            }
        }
    }

    private fun sha256Matches(file: File, expected: String): Boolean {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(1024 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                digest.update(buf, 0, n)
            }
        }
        val got = digest.digest().joinToString("") { "%02x".format(it) }
        return got == expected
    }
}
