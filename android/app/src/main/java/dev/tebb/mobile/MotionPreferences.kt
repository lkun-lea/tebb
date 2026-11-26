package dev.tebb.mobile

import android.content.Context
import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext

/** 用户可单独减少动效。系统关闭动画时优先即时呈现，不影响业务等待和回执。 */
internal val LocalReducedMotion = compositionLocalOf { false }

/** 同时监听系统动画倍率及应用内选择，使设置变更立即传递给当前屏幕。 */
@Composable
internal fun MotionPreferences(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val preferences = remember(context) { context.getSharedPreferences("appearance", Context.MODE_PRIVATE) }
    fun systemDisabled() = Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    var system by remember { mutableStateOf(systemDisabled()) }
    var reduced by remember { mutableStateOf(preferences.getBoolean("reduceMotion", false)) }
    DisposableEffect(context) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { system = systemDisabled() }
        }
        val listener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { prefs, key ->
            if (key == "reduceMotion") reduced = prefs.getBoolean(key, false)
        }
        context.contentResolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        preferences.registerOnSharedPreferenceChangeListener(listener)
        onDispose {
            context.contentResolver.unregisterContentObserver(observer)
            preferences.unregisterOnSharedPreferenceChangeListener(listener)
        }
    }
    CompositionLocalProvider(LocalReducedMotion provides (system || reduced), content = content)
}
