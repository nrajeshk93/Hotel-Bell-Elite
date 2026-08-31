package com.hotelbellelite.hbe

import android.content.Context
import android.view.inputmethod.InputMethodManager
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stores the last successful username/password in the Android Keystore and
 * unlocks them with the phone fingerprint (or other biometric).
 */
object HbeBiometric {
    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "hbe_fp_login_v1"
    private const val PREFS = "hbe_fp_login"
    private const val PREF_USER = "username"
    private const val PREF_BLOB = "blob"
    private const val PREF_IV = "iv"
    private const val PREF_ON = "enabled"
    private const val GCM_TAG_BITS = 128

    @Volatile var heldUsername: String? = null
    @Volatile var heldPassword: String? = null

    fun hold(username: String, password: String) {
        heldUsername = username.trim()
        heldPassword = password
    }

    fun clearHold() {
        heldUsername = null
        heldPassword = null
    }

    fun hasHold(): Boolean {
        return !heldUsername.isNullOrBlank() && !heldPassword.isNullOrEmpty()
    }

    private fun prefs(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun authenticators(): Int {
        return BiometricManager.Authenticators.BIOMETRIC_STRONG or
            BiometricManager.Authenticators.BIOMETRIC_WEAK
    }

    fun status(ctx: Context): JSONObject {
        val can = BiometricManager.from(ctx).canAuthenticate(authenticators())
        val available = can == BiometricManager.BIOMETRIC_SUCCESS
        val p = prefs(ctx)
        val enabled = p.getBoolean(PREF_ON, false) && !p.getString(PREF_BLOB, null).isNullOrBlank()
        return JSONObject()
            .put("ok", true)
            .put("native", true)
            .put("available", available)
            .put("canCode", can)
            .put("enabled", enabled)
            .put("hasHold", hasHold())
            .put("username", if (enabled) p.getString(PREF_USER, "") else "")
    }

    fun disable(ctx: Context) {
        prefs(ctx).edit().clear().apply()
        try {
            val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
            if (ks.containsAlias(KEY_ALIAS)) ks.deleteEntry(KEY_ALIAS)
        } catch (_: Exception) {
            // Best-effort key cleanup.
        }
    }

    fun enable(
        activity: FragmentActivity,
        username: String,
        password: String,
        done: (JSONObject) -> Unit,
    ) {
        val available = status(activity).optBoolean("available")
        if (!available) {
            done(
                JSONObject()
                    .put("ok", false)
                    .put("error", "Set up a fingerprint on this phone first."),
            )
            return
        }
        val user = username.trim()
        if (user.isEmpty() || password.isEmpty()) {
            done(
                JSONObject()
                    .put("ok", false)
                    .put("error", "Enter your password to enable fingerprint."),
            )
            return
        }
        prompt(
            activity,
            title = "Enable fingerprint",
            subtitle = "Confirm your fingerprint to sign in next time",
            onOk = {
                try {
                    save(activity, user, password)
                    done(JSONObject().put("ok", true).put("username", user).put("enabled", true))
                } catch (_: Exception) {
                    done(JSONObject().put("ok", false).put("error", "Could not save fingerprint login."))
                }
            },
            onFail = { msg ->
                done(JSONObject().put("ok", false).put("error", msg))
            },
        )
    }

    fun unlock(
        activity: FragmentActivity,
        done: (JSONObject) -> Unit,
    ) {
        val p = prefs(activity)
        if (!p.getBoolean(PREF_ON, false) || p.getString(PREF_BLOB, null).isNullOrBlank()) {
            done(JSONObject().put("ok", false).put("error", "Fingerprint is not enabled."))
            return
        }
        if (!status(activity).optBoolean("available")) {
            done(
                JSONObject()
                    .put("ok", false)
                    .put("error", "Set up a fingerprint on this phone first."),
            )
            return
        }
        prompt(
            activity,
            title = "Sign in",
            subtitle = "Use your fingerprint",
            onOk = {
                try {
                    val creds = load(activity)
                    done(
                        JSONObject()
                            .put("ok", true)
                            .put("username", creds.first)
                            .put("password", creds.second),
                    )
                } catch (_: Exception) {
                    disable(activity)
                    done(
                        JSONObject()
                            .put("ok", false)
                            .put("error", "Fingerprint login expired. Sign in with your password."),
                    )
                }
            },
            onFail = { msg ->
                done(JSONObject().put("ok", false).put("error", msg))
            },
        )
    }

    private fun prompt(
        activity: FragmentActivity,
        title: String,
        subtitle: String,
        onOk: () -> Unit,
        onFail: (String) -> Unit,
    ) {
        if (activity.isFinishing || activity.isDestroyed) {
            onFail("Fingerprint is not available right now.")
            return
        }
        try {
            val imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
            val token = activity.currentFocus?.windowToken
                ?: activity.window?.decorView?.windowToken
            if (token != null) {
                imm?.hideSoftInputFromWindow(token, 0)
            }
        } catch (_: Exception) {
            // Keyboard may already be closed.
        }
        val info = try {
            BiometricPrompt.PromptInfo.Builder()
                .setTitle(title)
                .setSubtitle(subtitle)
                .setNegativeButtonText("Use password")
                .setAllowedAuthenticators(authenticators())
                .build()
        } catch (_: Exception) {
            try {
                BiometricPrompt.PromptInfo.Builder()
                    .setTitle(title)
                    .setSubtitle(subtitle)
                    .setNegativeButtonText("Use password")
                    .build()
            } catch (_: Exception) {
                onFail("Could not open fingerprint.")
                return
            }
        }
        try {
            val biometricPrompt = BiometricPrompt(
                activity,
                ContextCompat.getMainExecutor(activity),
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                        onOk()
                    }

                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                        if (
                            errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON ||
                            errorCode == BiometricPrompt.ERROR_USER_CANCELED ||
                            errorCode == BiometricPrompt.ERROR_CANCELED
                        ) {
                            onFail("")
                            return
                        }
                        onFail(errString.toString().ifBlank { "Fingerprint did not work." })
                    }
                },
            )
            biometricPrompt.authenticate(info)
        } catch (_: Exception) {
            onFail("Could not open fingerprint.")
        }
    }

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        val existing = ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry
        if (existing != null) return existing.secretKey
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        gen.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return gen.generateKey()
    }

    private fun save(ctx: Context, username: String, password: String) {
        val payload = JSONObject()
            .put("u", username)
            .put("p", password)
            .toString()
            .toByteArray(StandardCharsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val iv = cipher.iv
        val blob = cipher.doFinal(payload)
        prefs(ctx).edit()
            .putBoolean(PREF_ON, true)
            .putString(PREF_USER, username)
            .putString(PREF_IV, Base64.encodeToString(iv, Base64.NO_WRAP))
            .putString(PREF_BLOB, Base64.encodeToString(blob, Base64.NO_WRAP))
            .apply()
    }

    private fun load(ctx: Context): Pair<String, String> {
        val p = prefs(ctx)
        val iv = Base64.decode(p.getString(PREF_IV, "") ?: "", Base64.NO_WRAP)
        val blob = Base64.decode(p.getString(PREF_BLOB, "") ?: "", Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
        val json = JSONObject(String(cipher.doFinal(blob), StandardCharsets.UTF_8))
        val user = json.optString("u")
        val pass = json.optString("p")
        if (user.isBlank() || pass.isEmpty()) throw IllegalStateException("empty")
        return user to pass
    }
}
