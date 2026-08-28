package com.hotelbellelite.hbemobile;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;

/**
 * Silent self-update via PackageInstaller Session API.
 *
 * Same package + same signing cert required. Reuse one keystore forever.
 * USER_ACTION_NOT_REQUIRED (API 31+) skips a custom in-app prompt. Android 14+
 * may still send STATUS_PENDING_USER_ACTION (system sheet) — we start that
 * intent. REQUEST_INSTALL_PACKAGES is a one-time OS grant: if
 * canRequestPackageInstalls() is false we open the system settings page.
 *
 * The install-status receiver is registered not-exported and ignores
 * broadcasts that do not match the session we created.
 */
public final class SilentUpdateHelper extends BroadcastReceiver {
    public static final String ACTION_INSTALL_STATUS =
            "com.hotelbellelite.hbemobile.INSTALL_STATUS";
    public static final String EXPECTED_PACKAGE = "com.hotelbellelite.hbemobile";
    private static final String TAG = "HbeSilentUpdate";
    private static final String SESSION_NAME = "hbemobile-ota";

    private static final SilentUpdateHelper INSTANCE = new SilentUpdateHelper();
    private static volatile boolean sReceiverRegistered = false;
    private static volatile int sSessionId = -1;
    private static volatile PackageInstaller.SessionCallback sCallback;

    private SilentUpdateHelper() {}

    public static boolean isDebuggable(Context context) {
        try {
            ApplicationInfo info = context.getApplicationInfo();
            return (info.flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        } catch (Exception e) {
            return false;
        }
    }

    public static String apkPackageName(Context context, String apkPath) {
        try {
            PackageManager pm = context.getApplicationContext().getPackageManager();
            PackageInfo info = pm.getPackageArchiveInfo(apkPath, 0);
            if (info == null || info.packageName == null) {
                return "";
            }
            return info.packageName;
        } catch (Exception e) {
            Log.w(TAG, "apkPackageName failed", e);
            return "";
        }
    }

    public static boolean canRequestPackageInstalls(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return true;
        }
        try {
            return context.getPackageManager().canRequestPackageInstalls();
        } catch (Exception e) {
            Log.w(TAG, "canRequestPackageInstalls failed", e);
            return false;
        }
    }

    public static void openUnknownSourcesSettings(Context context) {
        Context app = context.getApplicationContext();
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
            intent.setData(Uri.parse("package:" + app.getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            app.startActivity(intent);
        } catch (Exception e) {
            Log.e(TAG, "open unknown-sources settings failed", e);
            try {
                Intent fallback = new Intent(Settings.ACTION_SECURITY_SETTINGS);
                fallback.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                app.startActivity(fallback);
            } catch (Exception ignored) {
                // Retry on next launch / periodic check.
            }
        }
    }

    /**
     * @return "started", "need_permission", or "error:..."
     */
    public static synchronized String installApk(Context context, String apkPath) {
        Context app = context.getApplicationContext();
        if (!canRequestPackageInstalls(app)) {
            openUnknownSourcesSettings(app);
            return "need_permission";
        }
        File apk = new File(apkPath);
        if (!apk.isFile() || apk.length() <= 0) {
            return "error:apk-missing";
        }
        String pkg = apkPackageName(app, apkPath);
        if (!EXPECTED_PACKAGE.equals(pkg)) {
            Log.e(TAG, "refusing apk package=" + pkg);
            return "error:package-mismatch";
        }
        PackageInstaller installer = app.getPackageManager().getPackageInstaller();
        registerReceiver(app);
        registerSessionCallback(app, installer);
        PackageInstaller.Session session = null;
        try {
            PackageInstaller.SessionParams params =
                    new PackageInstaller.SessionParams(
                            PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(app.getPackageName());
            params.setSize(apk.length());
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                params.setRequireUserAction(
                        PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            }
            int sessionId = installer.createSession(params);
            sSessionId = sessionId;
            session = installer.openSession(sessionId);
            InputStream in = new FileInputStream(apk);
            try {
                OutputStream out = session.openWrite(SESSION_NAME, 0, apk.length());
                try {
                    byte[] buffer = new byte[65536];
                    int n;
                    while ((n = in.read(buffer)) != -1) {
                        out.write(buffer, 0, n);
                    }
                    session.fsync(out);
                } finally {
                    out.close();
                }
            } finally {
                in.close();
            }
            Intent broadcast = new Intent(ACTION_INSTALL_STATUS);
            broadcast.setPackage(app.getPackageName());
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                flags |= PendingIntent.FLAG_MUTABLE;
            }
            PendingIntent pending =
                    PendingIntent.getBroadcast(app, sessionId, broadcast, flags);
            session.commit(pending.getIntentSender());
            session.close();
            session = null;
            Log.i(TAG, "session " + sessionId + " committed");
            return "started";
        } catch (Exception e) {
            Log.e(TAG, "installApk failed", e);
            if (session != null) {
                try {
                    session.abandon();
                } catch (Exception ignored) {
                }
                try {
                    session.close();
                } catch (Exception ignored) {
                }
            }
            return "error:" + e.getClass().getSimpleName();
        }
    }

    private static void registerReceiver(Context app) {
        if (sReceiverRegistered) {
            return;
        }
        IntentFilter filter = new IntentFilter(ACTION_INSTALL_STATUS);
        try {
            // RECEIVER_NOT_EXPORTED = 0x4. Use reflection so this compiles on SDK 31.
            if (Build.VERSION.SDK_INT >= 33) {
                Method method =
                        Context.class.getMethod(
                                "registerReceiver",
                                BroadcastReceiver.class,
                                IntentFilter.class,
                                int.class);
                method.invoke(app, INSTANCE, filter, 0x4);
            } else {
                app.registerReceiver(INSTANCE, filter);
            }
            sReceiverRegistered = true;
        } catch (Exception e) {
            Log.e(TAG, "registerReceiver failed", e);
            try {
                app.registerReceiver(INSTANCE, filter);
                sReceiverRegistered = true;
            } catch (Exception ignored) {
            }
        }
    }

    private static void registerSessionCallback(Context app, PackageInstaller installer) {
        if (sCallback != null) {
            return;
        }
        final Context appCtx = app;
        sCallback =
                new PackageInstaller.SessionCallback() {
                    @Override
                    public void onCreated(int sessionId) {}

                    @Override
                    public void onBadgingChanged(int sessionId) {}

                    @Override
                    public void onActiveChanged(int sessionId, boolean active) {}

                    @Override
                    public void onProgressChanged(int sessionId, float progress) {}

                    @Override
                    public void onFinished(int sessionId, boolean success) {
                        if (sessionId != sSessionId) {
                            return;
                        }
                        Log.i(TAG, "session finished success=" + success);
                        if (success) {
                            relaunch(appCtx);
                        }
                    }
                };
        try {
            installer.registerSessionCallback(sCallback, new Handler(Looper.getMainLooper()));
        } catch (Exception e) {
            Log.e(TAG, "registerSessionCallback failed", e);
            sCallback = null;
        }
    }

    private static void relaunch(Context context) {
        try {
            PackageManager pm = context.getPackageManager();
            Intent launch = pm.getLaunchIntentForPackage(context.getPackageName());
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(launch);
                Log.i(TAG, "relaunched after silent install");
            }
        } catch (Exception e) {
            Log.e(TAG, "relaunch failed", e);
        }
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_INSTALL_STATUS.equals(intent.getAction())) {
            return;
        }
        int sessionId = intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -1);
        if (sSessionId < 0 || sessionId != sSessionId) {
            Log.w(TAG, "ignoring install broadcast session=" + sessionId);
            return;
        }
        int status =
                intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        Log.i(TAG, "install status=" + status + " msg=" + message);
        Context app = context.getApplicationContext();
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            startConfirmIntent(app, intent);
        } else if (status == PackageInstaller.STATUS_SUCCESS) {
            relaunch(app);
        } else {
            Log.w(TAG, "install not successful: " + status);
        }
    }

    @SuppressWarnings("deprecation")
    private static void startConfirmIntent(Context app, Intent statusIntent) {
        try {
            Intent confirm = statusIntent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                app.startActivity(confirm);
            }
        } catch (Exception e) {
            Log.e(TAG, "STATUS_PENDING_USER_ACTION start failed", e);
        }
    }
}
