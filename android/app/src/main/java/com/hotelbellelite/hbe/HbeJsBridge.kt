package com.hotelbellelite.hbe

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * JS ↔ native bridge for the bundled WebView UI.
 * Exposed as window.HBEAndroid from MainActivity.
 */
class HbeJsBridge(
    context: Context,
    private val onNotifications: (JSONArray) -> Unit,
) {
    private val appContext = context.applicationContext
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
}
