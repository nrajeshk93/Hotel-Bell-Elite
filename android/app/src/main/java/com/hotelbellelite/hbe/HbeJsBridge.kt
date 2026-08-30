package com.hotelbellelite.hbe

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject
import java.lang.ref.WeakReference
import java.util.concurrent.Executors

/**
 * JS ↔ native bridge for the bundled WebView UI.
 * Exposed as window.HBEAndroid from MainActivity.
 */
class HbeJsBridge(
    activity: AppCompatActivity,
    private val webView: () -> WebView?,
    private val onNotifications: (JSONArray) -> Unit,
) {
    private val activityRef = WeakReference(activity)
    private val appContext = activity.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()

    @JavascriptInterface
    fun postNotifications(json: String?) {
        if (json.isNullOrBlank()) return
        try {
            onNotifications(JSONArray(json))
        } catch (_: Exception) {
            // Ignore malformed payloads from the WebView.
        }
    }

    @JavascriptInterface
    fun haptic(kind: String) {
        val ms = when (kind.lowercase()) {
            "success" -> 30L
            "warning" -> 40L
            else -> 20L // light
        }
        try {
            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val manager = appContext.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                manager.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                appContext.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            if (!vibrator.hasVibrator()) return
            vibrator.vibrate(
                VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE),
            )
        } catch (_: SecurityException) {
            // VIBRATE permission missing on some devices.
        } catch (_: Exception) {
            // No vibrator hardware / service.
        }
    }

    @JavascriptInterface
    fun getAppVersion(): String {
        return try {
            val info = appContext.packageManager.getPackageInfo(appContext.packageName, 0)
            val code = if (Build.VERSION.SDK_INT >= 28) {
                info.longVersionCode.toInt()
            } else {
                @Suppress("DEPRECATION")
                info.versionCode
            }
            JSONObject()
                .put("version", info.versionName ?: BuildConfig.VERSION_NAME)
                .put("versionCode", code)
                .toString()
        } catch (_: Exception) {
            JSONObject()
                .put("version", BuildConfig.VERSION_NAME)
                .put("versionCode", BuildConfig.VERSION_CODE)
                .toString()
        }
    }

    @JavascriptInterface
    fun getUpdateStatus(): String = AppUpdater.statusJson()

    @JavascriptInterface
    fun checkForUpdate(): String {
        io.execute { AppUpdater.checkNow(appContext) }
        return "ok"
    }

    @JavascriptInterface
    fun installUpdate(): String {
        io.execute { AppUpdater.installDownloaded(appContext) }
        return "ok"
    }

    @JavascriptInterface
    fun installUpdateManual(): String {
        main.post { AppUpdater.installDownloadedManual(appContext) }
        return "ok"
    }

    @JavascriptInterface
    fun openInstallPermissionSettings(): String {
        main.post { SilentUpdateHelper.openUnknownSourcesSettings(appContext) }
        return "ok"
    }

    @JavascriptInterface
    fun biometricStatus(): String = HbeBiometric.status(appContext).toString()

    @JavascriptInterface
    fun holdLogin(username: String?, password: String?): String {
        val user = username?.trim().orEmpty()
        val pass = password.orEmpty()
        if (user.isEmpty() || pass.isEmpty()) {
            return JSONObject().put("ok", false).toString()
        }
        HbeBiometric.hold(user, pass)
        return JSONObject().put("ok", true).toString()
    }

    @JavascriptInterface
    fun clearHeldLogin(): String {
        HbeBiometric.clearHold()
        return JSONObject().put("ok", true).toString()
    }

    @JavascriptInterface
    fun hasHeldLogin(): String = if (HbeBiometric.hasHold()) "1" else "0"

    @JavascriptInterface
    fun enableBiometric(username: String?, password: String?): String {
        var user = username?.trim().orEmpty()
        var pass = password.orEmpty()
        if (user.isEmpty() || pass.isEmpty()) {
            user = HbeBiometric.heldUsername?.trim().orEmpty()
            pass = HbeBiometric.heldPassword.orEmpty()
        }
        if (user.isEmpty() || pass.isEmpty()) {
            return JSONObject()
                .put("ok", false)
                .put("error", "Enter your password to enable fingerprint.")
                .put("needPassword", true)
                .toString()
        }
        main.post {
            val act = activityRef.get() ?: return@post
            HbeBiometric.enable(act, user, pass) { result ->
                dispatchJs("window.__hbeOnBiometricEnable && window.__hbeOnBiometricEnable($result)")
            }
        }
        return JSONObject().put("ok", true).put("pending", true).toString()
    }

    @JavascriptInterface
    fun disableBiometric(): String {
        HbeBiometric.disable(appContext)
        return JSONObject().put("ok", true).put("enabled", false).toString()
    }

    @JavascriptInterface
    fun unlockWithBiometric(): String {
        main.post {
            val act = activityRef.get() ?: return@post
            HbeBiometric.unlock(act) { result ->
                dispatchJs("window.__hbeOnBiometricUnlock && window.__hbeOnBiometricUnlock($result)")
            }
        }
        return JSONObject().put("ok", true).put("pending", true).toString()
    }

    private fun dispatchJs(expr: String) {
        main.post {
            val wv = webView() ?: return@post
            wv.evaluateJavascript(expr, null)
        }
    }
}
