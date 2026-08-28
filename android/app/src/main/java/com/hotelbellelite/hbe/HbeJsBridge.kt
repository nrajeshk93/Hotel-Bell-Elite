package com.hotelbellelite.hbe

import android.webkit.JavascriptInterface
import org.json.JSONArray

/**
 * JS ↔ native bridge for the bundled WebView UI.
 * Exposed as window.HBEAndroid from MainActivity.
 */
class HbeJsBridge(
    private val onNotifications: (JSONArray) -> Unit,
) {
    @JavascriptInterface
    fun postNotifications(json: String?) {
        if (json.isNullOrBlank()) return
        try {
            onNotifications(JSONArray(json))
        } catch (_: Exception) {
            // Ignore malformed payloads from the WebView.
        }
    }
}
