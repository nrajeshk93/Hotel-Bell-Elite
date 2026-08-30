package com.hotelbellelite.hbe

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.hotelbellelite.hbe.databinding.ActivityMainBinding
import org.json.JSONArray

/**
 * Native Android shell paints bundled assets first, then refreshes from production
 * (/mobile-app/?v=VERSION) so HTML/CSS/JS updates reach phones after AWS sync.
 * Assets remain the fallback if remote fails. Native shell bumps still use silent OTA.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var lastErrorUrl: String? = null
    private var pendingOpenScreen: String? = null
    private var loadedAsset = false
    private var attemptedRemote = false
    private var lastBackExitAt = 0L
    private val assetEntryUrl = "file:///android_asset/mobile/mobile_ui_preview.html"
    private val remoteEntryUrl: String
        get() {
            val raw = BuildConfig.SERVER_URL.trim().ifEmpty {
                "https://belleliteaccounts.com/mobile-app/"
            }
            val base = if (raw.endsWith("/")) raw else "$raw/"
            // Cache-bust only when the APK version changes, not on every launch.
            return "$base?v=${BuildConfig.VERSION_NAME}"
        }
    private val apiHost = "belleliteaccounts.com"

    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = filePathCallback
            filePathCallback = null
            if (callback == null) return@registerForActivityResult

            val uris = if (result.resultCode == Activity.RESULT_OK) {
                WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            } else {
                null
            }
            callback.onReceiveValue(uris)
        }

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* no-op */ }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            show(WindowInsetsCompat.Type.statusBars())
        }
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        // Keep the system status bar (signal, battery, time) in its own strip.
        // Pad the WebView below it so the app does not draw over those icons.
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        HbeNotifications.ensureChannel(this)
        requestNotificationPermissionIfNeeded()
        pendingOpenScreen = HbeNotifications.openScreenFromIntent(intent)

        setupWebView()
        binding.retryButton.setOnClickListener {
            hideOffline()
            loadedAsset = false
            attemptedRemote = false
            loadAssetUi()
        }

        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    // Prefer in-app navigation stack over WebView browser history.
                    binding.webView.evaluateJavascript(
                        """
                        (function(){
                          try {
                            if (typeof window.hbeHandleBack === 'function') {
                              return window.hbeHandleBack() ? '1' : '0';
                            }
                            if (typeof window.goBack === 'function') {
                              return window.goBack() ? '1' : '0';
                            }
                          } catch (e) {}
                          return '0';
                        })();
                        """.trimIndent(),
                    ) { raw ->
                        val handled = raw == "1" || raw == "\"1\"" || raw == "true" || raw == "\"true\""
                        if (!handled) {
                            runOnUiThread {
                                val now = System.currentTimeMillis()
                                if (now - lastBackExitAt <= 2_000L) {
                                    finish()
                                } else {
                                    lastBackExitAt = now
                                    Toast.makeText(
                                        this@MainActivity,
                                        R.string.press_back_again,
                                        Toast.LENGTH_SHORT,
                                    ).show()
                                }
                            }
                        }
                    }
                }
            },
        )

        if (savedInstanceState != null) {
            binding.webView.restoreState(savedInstanceState)
        } else {
            loadAssetUi()
        }
        AppUpdater.onStatus = { json ->
            runOnUiThread {
                binding.webView.evaluateJavascript(
                    "window.__hbeOnUpdateStatus && window.__hbeOnUpdateStatus($json);",
                    null,
                )
            }
        }
        AppUpdater.attach(this)
        AppUpdater.checkSoon(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val screen = HbeNotifications.openScreenFromIntent(intent) ?: return
        pendingOpenScreen = screen
        deliverPendingOpenScreen()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        binding.webView.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        CookieManager.getInstance().flush()
        AppUpdater.checkSoon(this, delayMs = 1_500L)
    }

    private fun loadAssetUi() {
        hideOffline()
        setFileOriginAccess(true)
        binding.webView.loadUrl(assetEntryUrl)
    }

    /** file:// UI must XHR https://belleliteaccounts.com; remote https UI must not. */
    @Suppress("DEPRECATION")
    private fun setFileOriginAccess(enabled: Boolean) {
        val settings = binding.webView.settings
        settings.allowUniversalAccessFromFileURLs = enabled
        settings.allowFileAccessFromFileURLs = enabled
    }

    private fun maybeLoadRemote() {
        if (attemptedRemote) return
        if (!isNetworkAvailable()) return
        attemptedRemote = true
        Log.i("HbeMain", "refreshing UI from remote")
        binding.webView.loadUrl(remoteEntryUrl)
    }

    private fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val webView = binding.webView
        val cookieManager = CookieManager.getInstance()
        cookieManager.setAcceptCookie(true)
        cookieManager.setAcceptThirdPartyCookies(webView, true)

        webView.addJavascriptInterface(
            HbeJsBridge(applicationContext) { items: JSONArray ->
                runOnUiThread {
                    HbeNotifications.showFromJson(this, items)
                }
            },
            "HBEAndroid",
        )

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = false
            displayZoomControls = false
            allowFileAccess = true
            allowContentAccess = true
            // Bundled UI must call https://belleliteaccounts.com APIs, not file-origin XHR.
            @Suppress("DEPRECATION")
            allowUniversalAccessFromFileURLs = false
            @Suppress("DEPRECATION")
            allowFileAccessFromFileURLs = false
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = if (BuildConfig.ALLOW_CLEARTEXT) {
                WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            } else {
                WebSettings.MIXED_CONTENT_NEVER_ALLOW
            }
            cacheMode = WebSettings.LOAD_DEFAULT
            userAgentString = "$userAgentString HBEAndroidApp/${BuildConfig.VERSION_NAME}"
        }
        webView.overScrollMode = View.OVER_SCROLL_NEVER
        webView.setBackgroundColor(ContextCompat.getColor(this, R.color.hbe_bg))

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?,
            ): Boolean {
                val url = request?.url?.toString() ?: return false
                // Keep mobile UI + API on production; block desktop web app pages.
                if (url.startsWith("file:///android_asset/mobile/")) {
                    return false
                }
                if (url.contains(apiHost) && (
                        url.contains("/mobile-app/") ||
                            url.contains("/preview-api/") ||
                            url.contains("/api/mobile/")
                        )
                ) {
                    return false
                }
                if (url.contains(apiHost)) {
                    return true
                }
                return handleExternalOrDownload(url)
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                binding.progressBar.visibility = View.VISIBLE
                hideOffline()
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                binding.progressBar.visibility = View.GONE
                CookieManager.getInstance().flush()
                val isAsset = url != null && url.startsWith("file:///android_asset/mobile/")
                val isRemoteApp = url != null && url.contains("/mobile-app/")
                if (isAsset || isRemoteApp) {
                    view?.evaluateJavascript(
                        """
                        (function(){
                          document.body.classList.add('is-bundled-app');
                          var banner = document.querySelector('.banner');
                          if (banner) banner.style.display = 'none';
                        })();
                        """.trimIndent(),
                        null,
                    )
                    deliverPendingOpenScreen()
                }
                if (isRemoteApp) {
                    setFileOriginAccess(false)
                }
                if (isAsset) {
                    loadedAsset = true
                    maybeLoadRemote()
                }
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                if (request?.isForMainFrame != true) return
                val failed = request.url?.toString().orEmpty()
                if (failed.startsWith("file:///android_asset/")) {
                    // Asset failed: try remote once, otherwise show offline. Do not loop.
                    if (!attemptedRemote && isNetworkAvailable()) {
                        maybeLoadRemote()
                        return
                    }
                    lastErrorUrl = assetEntryUrl
                    showOffline()
                    return
                }
                // Remote main-frame failed — stay on bundled assets if they already painted.
                Log.w("HbeMain", "remote UI failed; staying on assets")
                if (loadedAsset) {
                    loadAssetUi()
                    return
                }
                lastErrorUrl = remoteEntryUrl
                showOffline()
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                binding.progressBar.progress = newProgress
                binding.progressBar.visibility =
                    if (newProgress in 1..99) View.VISIBLE else View.GONE
            }

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?,
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback
                val intent = fileChooserParams?.createIntent()
                    ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                    }
                return try {
                    fileChooserLauncher.launch(intent)
                    true
                } catch (_: ActivityNotFoundException) {
                    this@MainActivity.filePathCallback = null
                    Toast.makeText(
                        this@MainActivity,
                        R.string.file_chooser_title,
                        Toast.LENGTH_SHORT,
                    ).show()
                    false
                }
            }
        }

        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            enqueueDownload(url, userAgent, contentDisposition, mimeType)
        }
    }

    private fun deliverPendingOpenScreen() {
        val screen = pendingOpenScreen ?: return
        pendingOpenScreen = null
        val safe = screen.replace("\\", "\\\\").replace("'", "\\'")
        binding.webView.evaluateJavascript(
            """
            (function(){
              try {
                if (typeof go === 'function') go('$safe');
                else window.__hbePendingScreen = '$safe';
              } catch (_e) {}
            })();
            """.trimIndent(),
            null,
        )
    }

    private fun handleExternalOrDownload(url: String): Boolean {
        val lower = url.lowercase()
        val looksLikeExport =
            lower.contains("/export") ||
                lower.contains("/download_") ||
                lower.contains("/report") ||
                lower.endsWith(".xlsx") ||
                lower.endsWith(".xls") ||
                lower.endsWith(".csv")

        if (looksLikeExport) {
            enqueueDownload(url, null, null, null)
            return true
        }

        val uri = Uri.parse(url)
        val scheme = uri.scheme?.lowercase()
        if (scheme != null && scheme != "http" && scheme != "https") {
            return try {
                startActivity(Intent(Intent.ACTION_VIEW, uri))
                true
            } catch (_: ActivityNotFoundException) {
                true
            }
        }
        return false
    }

    private fun enqueueDownload(
        url: String,
        userAgent: String?,
        contentDisposition: String?,
        mimeType: String?,
    ) {
        try {
            val fileName = URLUtil.guessFileName(
                url,
                contentDisposition,
                mimeType ?: "application/octet-stream",
            )
            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setMimeType(mimeType ?: "application/octet-stream")
                addRequestHeader("User-Agent", userAgent ?: binding.webView.settings.userAgentString)
                val cookies = CookieManager.getInstance().getCookie(url)
                if (!cookies.isNullOrBlank()) {
                    addRequestHeader("Cookie", cookies)
                }
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                // App-specific folder — no storage permission required (API 26+).
                setDestinationInExternalFilesDir(
                    this@MainActivity,
                    Environment.DIRECTORY_DOWNLOADS,
                    fileName,
                )
                setTitle(fileName)
                setDescription(getString(R.string.app_name))
                setAllowedOverMetered(true)
                setAllowedOverRoaming(true)
            }
            val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
            Toast.makeText(this, R.string.download_started, Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            // Fallback: open in external browser / Sheets handler
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            } catch (_: ActivityNotFoundException) {
                Toast.makeText(this, e.message ?: "Download failed", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun showOffline() {
        binding.offlinePanel.visibility = View.VISIBLE
        binding.webView.visibility = View.INVISIBLE
        binding.progressBar.visibility = View.GONE
    }

    private fun hideOffline() {
        binding.offlinePanel.visibility = View.GONE
        binding.webView.visibility = View.VISIBLE
    }
}
