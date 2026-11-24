package dev.tebb.mobile

import android.util.Patterns
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 登录完成后恢复用户刚才选择的入口。首次启动登录成功时直接显示主聊。 */
internal enum class LoginDestination { Cloud, Computer }

private val suffixes = listOf("qq.com", "163.com", "gmail.com", "outlook.com")
private val fieldShape = RoundedCornerShape(16.dp)
private val accent = Color(0xFFBDCEA9)
private val field = Color(0xFF252828)

/** 保留邮箱用户名及别名，只替换域名。空用户名不会生成残缺地址。 */
internal fun withEmailSuffix(email: String, suffix: String): String {
    val user = email.substringBefore('@').trim()
    return if (user.isEmpty()) email else "$user@$suffix"
}

/** 桌宠沿用主聊的呼吸、眨眼和点按反馈。光晕与地面投影随布局尺寸绘制。 */
@Composable
private fun LoginPet() {
    Box(Modifier.size(width = 210.dp, height = 152.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            drawCircle(Brush.radialGradient(listOf(accent.copy(alpha = .16f), Color.Transparent),
                center, size.height * .49f), radius = size.height * .49f)
            val orbit = Size(size.width * .62f, size.height * .16f)
            drawOval(accent.copy(alpha = .21f), Offset(center.x - orbit.width / 2, size.height * .74f),
                orbit, style = Stroke(1.dp.toPx()))
        }
        Box(Modifier.size(86.dp)) {
            val half = with(LocalDensity.current) { 43.dp.toPx() }
            ChatPet(Offset(half, half), 86.dp, waiting = false, listening = false, location = "登录页", pendingCount = 0)
        }
    }
}

/** 竖屏将桌宠放在表单上沿，横屏并排。跳过与系统返回均沿用本地访客入口。 */
@Composable
internal fun LoginScreen(state: PairingState, authenticate: (String, String) -> Unit, skip: () -> Unit) {
    var email by rememberSaveable { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    val busy = state == PairingState.Connecting
    val valid = Patterns.EMAIL_ADDRESS.matcher(email.trim()).matches()
    val editEmail: (String) -> Unit = { value ->
        if (email != value) { email = value; code = "" }
    }
    BackHandler { if (!busy) skip() }
    MaterialTheme(colors = darkColors(primary = accent, background = Color(0xFF141617))) {
        Surface(color = MaterialTheme.colors.background, contentColor = Color(0xFFF2F1EB)) {
            BoxWithConstraints(Modifier.fillMaxSize().imePadding()) {
                val wide = maxWidth >= 600.dp && maxWidth > maxHeight
                val height = maxHeight
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min = height)
                    .padding(horizontal = 24.dp, vertical = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Row(Modifier.widthIn(max = 740.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("tebb.", fontSize = 24.sp, fontWeight = FontWeight.Bold)
                        TextButton(skip, enabled = !busy) { Text("跳过登录") }
                    }
                    Spacer(Modifier.weight(1f))
                    val form: @Composable () -> Unit = {
                        Column(Modifier.widthIn(max = 400.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            val colors = TextFieldDefaults.textFieldColors(backgroundColor = field,
                                focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                                disabledIndicatorColor = Color.Transparent)
                            TextField(email, editEmail, Modifier.fillMaxWidth(), enabled = !busy, shape = fieldShape,
                                colors = colors, singleLine = true, label = { Text("邮箱") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
                            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                suffixes.forEach { suffix ->
                                    val selected = email.substringAfter('@', "").equals(suffix, ignoreCase = true)
                                    val enabled = !busy && email.substringBefore('@').isNotBlank()
                                    Box(Modifier.heightIn(min = 48.dp).selectable(selected, enabled = enabled, role = Role.RadioButton,
                                        onClick = { editEmail(withEmailSuffix(email, suffix)) }), contentAlignment = Alignment.Center) {
                                        Text("@$suffix", Modifier.clip(fieldShape).background(if (selected) accent else field)
                                            .padding(horizontal = 10.dp, vertical = 6.dp),
                                            color = if (selected) Color(0xFF171B16) else Color(0xFFC2C7BF), fontSize = 13.sp)
                                    }
                                }
                            }
                            TextField(code, { code = it }, Modifier.fillMaxWidth(), enabled = !busy, shape = fieldShape,
                                colors = colors, singleLine = true, label = { Text("验证码") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                trailingIcon = { TextButton({ authenticate(email, "") }, enabled = !busy && valid) { Text("获取验证码") } })
                            (state as? PairingState.Notice)?.let { Text(it.message, fontSize = 14.sp) }
                            Spacer(Modifier.height(4.dp))
                            Button({ authenticate(email, code) }, Modifier.fillMaxWidth().heightIn(min = 52.dp), shape = fieldShape,
                                enabled = !busy && valid && code.isNotBlank()) { Text(if (busy) "请稍候…" else "登录") }
                        }
                    }
                    if (wide) {
                        Row(Modifier.widthIn(max = 740.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween) {
                            LoginPet()
                            Box(Modifier.weight(1f).padding(start = 24.dp), contentAlignment = Alignment.CenterEnd) { form() }
                        }
                    } else {
                        LoginPet()
                        Spacer(Modifier.height(16.dp))
                        form()
                    }
                    Spacer(Modifier.weight(1f))
                    Spacer(Modifier.height(20.dp))
                }
            }
        }
    }
}
