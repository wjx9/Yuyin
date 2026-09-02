allprojects {
    repositories {
        google()
        mavenCentral()
        // 高德 Maven 仓库（Agent SDK，尝试多个地址）
        maven { url = uri("https://developer.amap.com/android/repo/") }
        // maven { url = uri("https://maven.amap.com/nexus/content/repositories/releases/") }
        // maven { url = uri("https://aamap.artifactory.alipay.com/android") }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
