plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "campus.app"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "campus.app"
        minSdk = 26
        targetSdk = 37
        versionCode = 4
        versionName = "0.3.0-dev.2"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = true
                packageScope = setOf("androidx.**", "kotlin.**", "kotlinx.**")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }

    /**
     * dev：连本机后端，日常开发用。
     * demo：完全离线的演示包，内置真实抓取快照，发给别人也能直接看。
     */
    flavorDimensions += "mode"
    productFlavors {
        create("dev") {
            dimension = "mode"
            buildConfigField("boolean", "OFFLINE_DEMO", "false")
        }
        create("demo") {
            dimension = "mode"
            buildConfigField("boolean", "OFFLINE_DEMO", "true")
            applicationIdSuffix = ".demo"
            versionNameSuffix = "-demo"
        }
    }
    testOptions {
        unitTests.all {
            // 本地真实后端集成测试用：默认跳过，只有显式传入 URL 时才执行。
            it.systemProperty(
                "campus.backend.url",
                System.getProperty("campus.backend.url") ?: "",
            )
        }
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.junit)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}