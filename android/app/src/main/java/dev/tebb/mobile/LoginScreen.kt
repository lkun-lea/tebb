package dev.tebb.mobile

import android.content.res.Configuration
import android.util.Patterns
import androidx.activity.compose.BackHandler
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 登录完成后恢复用户刚才选择的入口。首次启动登录成功时直接显示主聊。 */
internal enum class LoginDestination { Cloud, Computer }

private val suffixes = listOf("gmail.com", "qq.com", "163.com", "outlook.com")
private val fieldShape = RoundedCornerShape(20.dp)
private val accent = Color(0xFF00A6F4)
private val field = Color(0xFF252828)

/** 桌宠沿用主聊的呼吸、眨眼和点按反馈。登录页使用原始配色。 */
@Composable
private fun LoginPet(diameter: Dp) {
    Box(Modifier.size(width = diameter * 1.85f, height = diameter * 1.55f), contentAlignment = Alignment.Center) {
        Box(Modifier.size(diameter)) {
            val half = with(LocalDensity.current) { diameter.toPx() / 2 }
            ChatPet(Offset(half, half), diameter, waiting = false, listening = false, location = "登录页", pendingCount = 0)
        }
    }
}

/** 竖屏将桌宠放在表单上沿，横屏并排。跳过与系统返回均沿用本地访客入口。 */
@Composable
internal fun LoginScreen(state: PairingState, authenticate: (String, String) -> Unit, skip: () -> Unit) {
    var email by rememberSaveable { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    val busy = state == PairingState.Connecting
    var suffix by rememberSaveable { mutableStateOf("gmail.com") }
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
                val wide = maxWidth >= 600.dp && LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
                val diameter = (maxWidth * .29f).coerceIn(112.dp, 174.dp)
                val height = maxHeight
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min = height)
                    .padding(horizontal = 24.dp, vertical = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Row(Modifier.widthIn(max = 920.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("tebb.", fontSize = 32.sp, fontWeight = FontWeight.Bold)
                        TextButton(skip, enabled = !busy) { Text("跳过登录", fontSize = 16.sp) }
                    }
                    Spacer(Modifier.weight(.75f))
                    val form: @Composable () -> Unit = {
                        Column(Modifier.widthIn(max = 560.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            Text("邮箱登录", fontSize = 29.sp, fontWeight = FontWeight.SemiBold)
                            val colors = TextFieldDefaults.textFieldColors(backgroundColor = field,
                                focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                                disabledIndicatorColor = Color.Transparent)
                            TextField(email, editEmail, Modifier.fillMaxWidth().heightIn(min = 70.dp), enabled = !busy, shape = fieldShape,
                                colors = colors, textStyle = MaterialTheme.typography.h6.copy(fontSize = 20.sp), singleLine = true, label = { Text("邮箱") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                                trailingIcon = {
                                    Box {
                                        TextButton({ menuOpen = true }, enabled = !busy,
                                            modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "选择邮箱域名" }) {
                                            if ('@' !in email) Text("@$suffix", fontSize = 17.sp)
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
                            TextField(code, { code = it }, Modifier.fillMaxWidth().heightIn(min = 70.dp), enabled = !busy, shape = fieldShape,
                                colors = colors, textStyle = MaterialTheme.typography.h6.copy(fontSize = 20.sp), singleLine = true, label = { Text("验证码") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                trailingIcon = { TextButton({ authenticate(address, "") }, enabled = !busy && valid) { Text("获取验证码", fontSize = 16.sp) } })
                            (state as? PairingState.Notice)?.let { Text(it.message, fontSize = 14.sp) }
                            Spacer(Modifier.height(4.dp))
                            Button({ authenticate(address, code) }, Modifier.fillMaxWidth().heightIn(min = 64.dp), shape = fieldShape,
                                colors = ButtonDefaults.buttonColors(backgroundColor = accent, contentColor = Color.White, disabledBackgroundColor = Color(0xFF373D36),
                                    disabledContentColor = Color(0xFFB2BAAE)),
                                enabled = !busy && valid && code.isNotBlank()) { Text(if (busy) "请稍候…" else "登录", fontSize = 19.sp) }
                        }
                    }
                    if (wide) {
                        Row(Modifier.widthIn(max = 920.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween) {
                            LoginPet(diameter)
                            Box(Modifier.weight(1f).padding(start = 24.dp), contentAlignment = Alignment.CenterEnd) { form() }
                        }
                    } else {
                        LoginPet(diameter)
                        Spacer(Modifier.height(26.dp))
                        form()
                    }
                    Spacer(Modifier.weight(1f))
                    Spacer(Modifier.height(20.dp))
                }
            }
        }
    }
}
