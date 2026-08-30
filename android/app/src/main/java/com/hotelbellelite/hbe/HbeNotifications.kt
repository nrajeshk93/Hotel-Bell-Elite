package com.hotelbellelite.hbe

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.toBitmap
import org.json.JSONArray

object HbeNotifications {
    const val CHANNEL_ID = "hbe_alerts"
    const val EXTRA_OPEN_SCREEN = "open_screen"
    private const val PREFS = "hbe_native_notifs"
    private const val KEY_SEEN = "seen_fingerprints"

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.notif_channel_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = context.getString(R.string.notif_channel_desc)
            enableVibration(true)
        }
        manager.createNotificationChannel(channel)
    }

    fun showFromJson(context: Context, items: JSONArray) {
        ensureChannel(context)
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val seen = prefs.getStringSet(KEY_SEEN, emptySet())?.toMutableSet() ?: mutableSetOf()
        val nextSeen = mutableSetOf<String>()

        for (i in 0 until items.length()) {
            val row = items.optJSONObject(i) ?: continue
            val id = row.optString("id").ifBlank { "item-$i" }
            val title = row.optString("title").ifBlank { context.getString(R.string.app_name) }
            val body = row.optString("body")
            val screen = row.optString("screen")
            val count = row.opt("count")?.toString().orEmpty()
            val fingerprint = "$id|$count|$title|$body"
            if (fingerprint in seen) {
                nextSeen.add(fingerprint)
                continue
            }

            val notifId = stableId(id)
            val intent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                if (screen.isNotBlank()) putExtra(EXTRA_OPEN_SCREEN, screen)
            }
            val pending = PendingIntent.getActivity(
                context,
                notifId,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_notification)
                .setLargeIcon(largeIconBitmap(context))
                .setColor(Color.WHITE)
                .setColorized(false)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pending)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .build()

            try {
                NotificationManagerCompat.from(context).notify(notifId, notification)
                nextSeen.add(fingerprint)
            } catch (_: SecurityException) {
                // Keep previous seen set; permission not granted yet.
                return
            }
        }

        prefs.edit().putStringSet(KEY_SEEN, nextSeen).apply()
    }

    fun openScreenFromIntent(intent: Intent?): String? {
        return intent?.getStringExtra(EXTRA_OPEN_SCREEN)?.takeIf { it.isNotBlank() }
    }


    private fun largeIconBitmap(context: Context): Bitmap {
        val drawable = ContextCompat.getDrawable(context, R.drawable.ic_notification_large)
            ?: return Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888)
        val size = (64f * context.resources.displayMetrics.density).toInt().coerceAtLeast(192)
        return drawable.toBitmap(width = size, height = size, config = Bitmap.Config.ARGB_8888)
    }

    private fun stableId(id: String): Int {

        var hash = 0
        for (ch in id) {
            hash = 31 * hash + ch.code
        }
        return hash and 0x7fffffff
    }
}
