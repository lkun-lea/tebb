package dev.tebb.mobile

import android.util.Patterns
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
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
    var suffix by rememberSaveable { mutableStateOf("") }
    var menuOpen by remember { mutableStateOf(false) }
    val input = email.trim()
    val address = if (input.isNotEmpty() && '@' !in input && suffix.isNotEmpty()) "$input@$suffix" else input
    val valid = Patterns.EMAIL_ADDRESS.matcher(address).matches()
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
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                                trailingIcon = {
                                    Box {
                                        TextButton({ menuOpen = true }, enabled = !busy,
                                            modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "选择邮箱后缀" }) {
                                            Text(if ('@' !in email && suffix.isNotEmpty()) "@$suffix" else "后缀")
                                            Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
                                        }
                                        DropdownMenu(menuOpen && !busy, onDismissRequest = { menuOpen = false }) {
                                            val current = if ('@' in email) email.substringAfter('@').trim() else suffix
                                            suffixes.forEach { domain ->
                                                DropdownMenuItem(onClick = {
                                                    if (!domain.equals(current, ignoreCase = true)) code = ""
                                                    email = email.substringBefore('@')
                                                    suffix = domain
                                                    menuOpen = false
                                                }) {
                                                    Text("@$domain", Modifier.weight(1f))
                                                    if (domain.equals(current, ignoreCase = true)) Text("✓", color = accent)
                                                }
                                            }
                                        }
                                    }
                                })
                            TextField(code, { code = it }, Modifier.fillMaxWidth(), enabled = !busy, shape = fieldShape,
                                colors = colors, singleLine = true, label = { Text("验证码") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                trailingIcon = { TextButton({ authenticate(address, "") }, enabled = !busy && valid) { Text("获取验证码") } })
                            (state as? PairingState.Notice)?.let { Text(it.message, fontSize = 14.sp) }
                            Spacer(Modifier.height(4.dp))
                            Button({ authenticate(address, code) }, Modifier.fillMaxWidth().heightIn(min = 52.dp), shape = fieldShape,
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
