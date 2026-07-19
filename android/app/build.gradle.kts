plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.hotelbellelite.hbe"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.hotelbellelite.hbe"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        debug {
            isDebuggable = true
            // Android emulator loopback → host machine Flask (app.py uses port 8002)
            buildConfigField("String", "SERVER_URL", "\"http://10.0.2.2:8002\"")
            buildConfigField("boolean", "ALLOW_CLEARTEXT", "true")
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // Change this to your real HTTPS host before shipping.
            buildConfigField("String", "SERVER_URL", "\"https://YOUR_HTTPS_HOST\"")
            buildConfigField("boolean", "ALLOW_CLEARTEXT", "false")
            manifestPlaceholders["usesCleartextTraffic"] = "false"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
}
