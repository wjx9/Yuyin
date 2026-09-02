plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.rayneo.moasm_vui"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.rayneo.moasm.vui"
        // 语音识别/TTS 插件要求 minSdk 21+；取 24（Android 7）更稳妥
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    // =====================================================================
    // 高德导航 SDK（无 UI 模式自定义导航界面）
    // =====================================================================
    implementation(files("libs/AMap3DMap_11.2.100_AMapNavi_11.2.100_AMapSearch_9.8.1_AMapLocation_11.2.100_20260805.aar"))

    // =====================================================================
    // 高德 LLM Agent SDK（POC 验证）——官方文档坐标：com.amap.lbs.client:amap-agent:1.1.41
    // 注意：该坐标在 developer.amap.com(404)、maven.amap.com(连接超时)、aamap.artifactory(DNS失败)
    //       均无法解析，当前网络环境下会阻塞构建。AgentPocActivity 走反射不依赖它编译期可用，
    //       故暂注释；待有仓库访问权限或拿到本地 AAR 后再放开。
    // =====================================================================
    // implementation("com.amap.lbs.client:amap-agent:1.1.41")

    // =====================================================================
    // 高德 AmapLinkClient SDK（可选，用于 IPC 控制高德地图）
    // =====================================================================
    // implementation(files("libs/amap-link-client.aar"))
}
