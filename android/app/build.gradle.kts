// 固定编译器与 Compose 插件版本，使本地构建可复现。
plugins {
    id("com.android.application") version "8.5.0"
    id("org.jetbrains.kotlin.android") version "1.9.0"
}

android {
    namespace = "dev.tebb.mobile"
    compileSdk = 34
    sourceSets.getByName("main").assets.srcDir("../../client/src/journal")
    // Java 与 Kotlin 统一生成 Java 17 字节码，打包时由 Android 工具链转换。
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    defaultConfig {
        applicationId = "dev.tebb.mobile"
        testInstrumentationRunner = "dev.tebb.mobile.PersonalAgentAcceptance"
        // 只嵌入项目公开配置，账号令牌在登录后由手机单独领取。
        for ((field, env) in mapOf("ACCOUNT_URL" to "TEBB_CLOUD_URL", "ACCOUNT_PUBLIC_KEY" to "TEBB_CLOUD_PUBLISHABLE_KEY")) {
            val value = providers.environmentVariable(env).orElse("").get()
            require(value.all { it.isLetterOrDigit() || it in ":/.-_=" })
            require(!value.startsWith("sb_secret_") && (field != "ACCOUNT_PUBLIC_KEY" || value.isEmpty() || value.startsWith("sb_publishable_"))) {
                "Android 构建只接受 Supabase publishable key"
            }
            buildConfigField("String", field, "\"$value\"")
        }
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
    }
    buildFeatures { compose = true; buildConfig = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.1" }
}

dependencies {
    implementation("net.java.dev.jna:jna:5.18.1@aar")
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    implementation("com.google.zxing:core:3.5.3")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.compose.material:material:1.5.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-savedstate:2.6.2")
    testImplementation("junit:junit:4.13.2")
}
