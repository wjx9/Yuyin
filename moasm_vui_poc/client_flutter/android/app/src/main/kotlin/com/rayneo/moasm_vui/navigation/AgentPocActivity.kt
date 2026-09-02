package com.rayneo.moasm_vui.navigation

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import com.rayneo.moasm_vui.R
import java.lang.reflect.Method

/**
 * 高德 Agent SDK POC 验证页面
 *
 * 验证三个关键问题：
 * 1. AMAP_SDK 模式是否不跳转高德App
 * 2. 非导航意图 Agent 返回什么
 * 3. 多轮对话是否正常
 *
 * 使用反射调用 Agent SDK，避免 API 差异导致编译失败。
 */
class AgentPocActivity : Activity() {

    companion object {
        private const val TAG = "AgentPoc"
    }

    // Agent SDK 相关对象（通过反射获取）
    private var mAMapApi: Any? = null
    private var mAgentClient: Any? = null
    private var mNaviClient: Any? = null
    private var mIsInitialized = false

    // UI
    private lateinit var etInput: EditText
    private lateinit var tvResult: TextView
    private lateinit var btnSend: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_agent_poc)

        etInput = findViewById(R.id.et_input)
        tvResult = findViewById(R.id.tv_result)
        btnSend = findViewById(R.id.btn_send)

        // 初始化 Agent SDK
        initAgentSdk()

        // 发送按钮
        btnSend.setOnClickListener {
            val query = etInput.text.toString().trim()
            if (query.isNotEmpty()) {
                sendToAgent(query)
            }
        }

        // 清空按钮
        findViewById<Button>(R.id.btn_clear).setOnClickListener {
            tvResult.text = "等待发送指令..."
        }

        // 快捷测试指令
        findViewById<Button>(R.id.btn_test1).setOnClickListener { sendToAgent("导航到大新") }
        findViewById<Button>(R.id.btn_test2).setOnClickListener { sendToAgent("第一个") }
        findViewById<Button>(R.id.btn_test3).setOnClickListener { sendToAgent("今天天气") }
        findViewById<Button>(R.id.btn_test4).setOnClickListener { sendToAgent("直接导航到大新，不要废话") }
        findViewById<Button>(R.id.btn_test5).setOnClickListener { sendToAgent("帮我设闹钟") }
        findViewById<Button>(R.id.btn_test6).setOnClickListener { sendToAgent("结束导航") }
    }

    /**
     * 初始化 Agent SDK（通过反射）
     */
    private fun initAgentSdk() {
        appendResult("=== 开始初始化 Agent SDK ===")

        try {
            // 1. 设置 API Key
            // AMapApi.setApiKey(context, key)
            val aMapApiClass = try {
                Class.forName("com.amap.lbs.client.api.AMapApi")
            } catch (e: ClassNotFoundException) {
                Class.forName("com.amap.api.agent.AMapApi")
            }
            appendResult("找到 AMapApi 类: ${aMapApiClass.name}")

            // setApiKey 静态方法
            try {
                val setApiKeyMethod = aMapApiClass.getMethod("setApiKey", android.content.Context::class.java, String::class.java)
                setApiKeyMethod.invoke(null, this, "a188be830fac2a043781b481c4a8dc27")
                appendResult("✓ API Key 设置成功")
            } catch (e: NoSuchMethodException) {
                appendResult("⚠ setApiKey 方法不存在，尝试其他方式")
            }

            // 2. 隐私合规
            try {
                val naviSettingClass = Class.forName("com.amap.api.navi.NaviSetting")
                val updatePrivacyShow = naviSettingClass.getMethod("updatePrivacyShow", android.content.Context::class.java, Boolean::class.javaPrimitiveType, Boolean::class.javaPrimitiveType)
                val updatePrivacyAgree = naviSettingClass.getMethod("updatePrivacyAgree", android.content.Context::class.java, Boolean::class.javaPrimitiveType)
                updatePrivacyShow.invoke(null, this, true, true)
                updatePrivacyAgree.invoke(null, this, true)
                appendResult("✓ 隐私合规设置成功")
            } catch (e: Exception) {
                appendResult("⚠ 隐私合规设置失败: ${e.message}")
            }

            // 3. 创建 AMapApi 实例
            try {
                val createMethod = aMapApiClass.getMethod("create")
                mAMapApi = createMethod.invoke(null)
                appendResult("✓ AMapApi 实例创建成功")
            } catch (e: NoSuchMethodException) {
                // 尝试构造函数
                try {
                    val constructor = aMapApiClass.getConstructor()
                    mAMapApi = constructor.newInstance()
                    appendResult("✓ AMapApi 实例创建成功（构造函数）")
                } catch (e2: Exception) {
                    appendResult("✗ AMapApi 实例创建失败: ${e2.message}")
                    return
                }
            }

            // 4. 创建 AMapContext
            try {
                val contextClass = Class.forName("com.amap.lbs.client.api.AMapContext")
                val contextConstructor = contextClass.getConstructor(android.content.Context::class.java)
                val aMapContext = contextConstructor.newInstance(this)
                appendResult("✓ AMapContext 创建成功")

                // 5. 初始化 SDK
                val initMethod = aMapApiClass.getMethod("init", contextClass)
                initMethod.invoke(mAMapApi, aMapContext)
                appendResult("✓ AMapApi.init() 调用成功")

                // 获取版本号
                try {
                    val getVersionMethod = aMapApiClass.getMethod("getVersion")
                    val version = getVersionMethod.invoke(mAMapApi)
                    appendResult("✓ Agent SDK 版本: $version")
                } catch (e: Exception) {
                    appendResult("⚠ 获取版本号失败: ${e.message}")
                }

                mIsInitialized = true
            } catch (e: Exception) {
                appendResult("✗ AMapContext/init 失败: ${e.message}")
                Log.e(TAG, "init failed", e)
                return
            }

            // 6. 获取 AgentClient
            try {
                val getAgentClientMethod = aMapApiClass.getMethod("getAgentClient")
                mAgentClient = getAgentClientMethod.invoke(mAMapApi)
                appendResult("✓ AgentClient 获取成功")

                // 设置命令执行目标为 AMAP_SDK（不跳转高德App）
                try {
                    val agentClientClass = mAgentClient!!.javaClass
                    val destinationEnum = Class.forName("\${agentClientClass.name}\$AgentCommandDestination")
                    val amapSdkValue = destinationEnum.getField("AMAP_SDK").get(null)
                    val setDestinationMethod = agentClientClass.getMethod("setAgentCommandDestination", destinationEnum)
                    setDestinationMethod.invoke(mAgentClient, amapSdkValue)
                    appendResult("✓ 命令执行目标设置为 AMAP_SDK（不跳转高德App）")
                } catch (e: Exception) {
                    appendResult("⚠ 设置命令执行目标失败: ${e.message}")
                }

                // 设置回调
                try {
                    val agentClientClass = mAgentClient!!.javaClass
                    val setCallbackMethod = agentClientClass.methods.find { it.name == "setAgentCallback" || it.name == "setCallback" }
                    if (setCallbackMethod != null) {
                        appendResult("✓ 找到回调设置方法: ${setCallbackMethod.name}")
                        // 回调通过动态代理实现
                        setupAgentCallback(agentClientClass, setCallbackMethod)
                    } else {
                        appendResult("⚠ 未找到回调设置方法")
                    }
                } catch (e: Exception) {
                    appendResult("⚠ 设置回调失败: ${e.message}")
                }
            } catch (e: Exception) {
                appendResult("✗ AgentClient 获取失败: ${e.message}")
            }

            // 7. 获取 NaviClient
            try {
                val getNaviClientMethod = aMapApiClass.getMethod("getNaviClient")
                mNaviClient = getNaviClientMethod.invoke(mAMapApi)
                appendResult("✓ NaviClient 获取成功")
            } catch (e: Exception) {
                appendResult("⚠ NaviClient 获取失败: ${e.message}")
            }

            appendResult("=== 初始化完成 ===\n")
            Toast.makeText(this, "Agent SDK 初始化完成", Toast.LENGTH_SHORT).show()

        } catch (e: Exception) {
            appendResult("✗ 初始化异常: ${e.javaClass.name}: ${e.message}")
            Log.e(TAG, "initAgentSdk failed", e)
            Toast.makeText(this, "初始化失败: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    /**
     * 设置 Agent 回调（动态代理）
     */
    private fun setupAgentCallback(agentClientClass: Class<*>, setCallbackMethod: Method) {
        try {
            // 查找回调接口
            val callbackInterface = setCallbackMethod.parameterTypes[0]
            appendResult("回调接口: ${callbackInterface.name}")

            // 创建动态代理
            val callbackProxy = java.lang.reflect.Proxy.newProxyInstance(
                callbackInterface.classLoader,
                arrayOf(callbackInterface)
            ) { _, method, args ->
                val methodName = method.name
                appendResult("\n--- Agent 回调: $methodName ---")
                if (args != null && args.isNotEmpty()) {
                    for (i in args.indices) {
                        appendResult("  arg[$i]: ${args[i]?.javaClass?.name} = ${args[i]}")
                        // 尝试打印对象的所有字段
                        try {
                            if (args[i] != null && args[i] !is String && args[i] !is Number) {
                                appendResult("  [对象详情]")
                                for (field in args[i]!!.javaClass.declaredFields) {
                                    field.isAccessible = true
                                    try {
                                        val value = field.get(args[i])
                                        appendResult("    ${field.name}: $value")
                                    } catch (e: Exception) {
                                        // ignore
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            // ignore
                        }
                    }
                }
                // 返回默认值
                when (method.returnType) {
                    Void.TYPE -> {}
                    Boolean::class.javaPrimitiveType -> return@newProxyInstance false
                    Int::class.javaPrimitiveType -> return@newProxyInstance 0
                    else -> return@newProxyInstance null
                }
                null
            }

            setCallbackMethod.invoke(mAgentClient, callbackProxy)
            appendResult("✓ Agent 回调设置成功（动态代理）")
        } catch (e: Exception) {
            appendResult("⚠ 设置回调代理失败: ${e.message}")
        }
    }

    /**
     * 发送用户指令给 Agent
     */
    private fun sendToAgent(query: String) {
        if (!mIsInitialized || mAgentClient == null) {
            appendResult("✗ Agent SDK 未初始化，无法发送")
            return
        }

        appendResult("\n>>> 用户输入: $query")

        try {
            val agentClientClass = mAgentClient!!.javaClass

            // 查找查询方法
            val queryMethod = agentClientClass.methods.find { method ->
                (method.name == "query" || method.name == "sendQuery" || method.name == "ask" || method.name == "process") &&
                        method.parameterTypes.size == 1 &&
                        method.parameterTypes[0] == String::class.java
            }

            if (queryMethod == null) {
                appendResult("✗ 未找到查询方法，可用方法:")
                for (m in agentClientClass.methods) {
                    appendResult("  ${m.name}(${m.parameterTypes.joinToString { it.simpleName }})")
                }
                return
            }

            appendResult("调用方法: ${queryMethod.name}")

            // 同步调用
            val result = queryMethod.invoke(mAgentClient, query)
            if (result != null) {
                appendResult("<<< Agent 返回: ${result.javaClass.name}")
                appendResult("    值: $result")
                // 打印对象字段
                try {
                    for (field in result.javaClass.declaredFields) {
                        field.isAccessible = true
                        try {
                            val value = field.get(result)
                            appendResult("    ${field.name}: $value")
                        } catch (e: Exception) {
                            // ignore
                        }
                    }
                } catch (e: Exception) {
                    // ignore
                }
            } else {
                appendResult("<<< Agent 返回: null（异步回调中处理）")
            }
        } catch (e: Exception) {
            appendResult("✗ 发送失败: ${e.javaClass.name}: ${e.message}")
            Log.e(TAG, "sendToAgent failed", e)
        }
    }

    /**
     * 追加结果到文本框
     */
    private fun appendResult(text: String) {
        runOnUiThread {
            val current = tvResult.text.toString()
            tvResult.text = if (current == "等待发送指令...") {
                text
            } else {
                "$current\n$text"
            }
            // 滚动到底部
            val scrollView = tvResult.parent as android.widget.ScrollView
            scrollView.post {
                scrollView.fullScroll(android.view.View.FOCUS_DOWN)
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        // 释放资源
        try {
            if (mAMapApi != null) {
                val destroyMethod = mAMapApi!!.javaClass.methods.find { it.name == "destroy" || it.name == "release" || it.name == "uninit" }
                destroyMethod?.invoke(mAMapApi)
            }
        } catch (e: Exception) {
            Log.e(TAG, "destroy failed", e)
        }
    }
}
