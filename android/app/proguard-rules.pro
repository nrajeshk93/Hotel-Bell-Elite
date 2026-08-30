# Hotel Bell Elite WebView shell — keep JS bridges and updater.
-keepattributes JavascriptInterface
-keepattributes *Annotation*

-keep class com.hotelbellelite.hbe.HbeJsBridge { *; }
-keepclassmembers class com.hotelbellelite.hbe.HbeJsBridge {
    @android.webkit.JavascriptInterface <methods>;
}

-keep class com.hotelbellelite.hbe.MainActivity { *; }
-keep class com.hotelbellelite.hbe.AppUpdater { *; }
-keep class com.hotelbellelite.hbe.HbeNotifications { *; }
-keep class com.hotelbellelite.hbe.HbeBiometric { *; }
-keep class com.hotelbellelite.hbe.SilentUpdateHelper { *; }

# Any WebView JS interfaces
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

-keep class com.hotelbellelite.hbe.BuildConfig { *; }
