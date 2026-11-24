// Android 插件来自 Google，Kotlin 与测试依赖也使用 Maven Central。
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = "TebbAndroid"
include(":app")
