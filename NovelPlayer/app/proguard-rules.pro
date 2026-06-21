# Add project specific ProGuard rules here.
-keepattributes *Annotation*
-keep class com.novelplayer.app.model.** { *; }
-keep class org.jsoup.** { *; }
-dontwarn org.jsoup.**
-dontwarn okhttp3.**
-dontwarn okio.**
