/**
 * API配置文件
 * 包含后端API基础URL和AI问答功能所需的API参数
 *
 * 密钥管理约定：不要把真实 Key 写进代码再提交。
 * 复制项目根目录的 .env.example 为 .env.local，填入自己的 Key：
 *     VITE_AI_API_KEY=sk-你的key
 * Vite 只会把 VITE_ 前缀的变量注入前端，未配置时自动回退到占位符，
 * 此时 AI 问答页会提示「API Key未配置」，不会带着无效 Key 去请求。
 */

// API基础URL配置
export const apiConfig = {
  // 后端API基础URL
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
}

export const aiChatConfig = {
  // OpenAI 兼容接口地址
  apiEndpoint: import.meta.env.VITE_AI_API_ENDPOINT
    || 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',

  // API Key（从环境变量读取；未配置时为空字符串，前端会提示未配置）
  apiKey: import.meta.env.VITE_AI_API_KEY || '',

  // 使用的模型
  model: import.meta.env.VITE_AI_MODEL || 'qwen3-max-preview',
}
