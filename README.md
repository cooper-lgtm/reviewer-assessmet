# 高級後端工程師（AI方向）- 編程評測

你好！

感謝你參與本次招聘流程。本次評測旨在考察你在AI應用開發領域的綜合能力，特別是利用大型語言模型（LLM）解決實際問題的工程、設計和創造能力。請仔細閱讀以下說明。

---

## 場景描述

你的任務是構建一個AI Agent。這個Agent能夠接收代碼和需求，然後對代碼進行分析，並輸出一份結構化的分析報告。Agent可以使用NodeJs/Python/N8N開發。

## Agent的輸入

你的Agent需要設計成一個接受 `multipart/form-data` 請求的API服務。該服務接收以下兩個部分：

1.  **`problem_description`** (string, form field): 一段描述項目應實現功能的自然語言文本。
2.  **`code_zip`** (file, form upload): 一個包含項目完整源代碼的zip壓縮文件。

## 核心任務 (必須完成)

**目標：生成一份代碼功能定位報告。**

Agent需要分析代碼，並輸出一份JSON報告。這份報告需要清晰地指出，為了實現`problem_description`中描述的各項功能，代碼倉庫中的哪些部分是關鍵的實現點。

**JSON報告結構示例：**

```json
{
  "feature_analysis": [
    {
      "feature_description": "實現`創建頻道`功能",
      "implementation_location": [
        {
          "file": "src/modules/channel/channel.resolver.ts",
          "function": "createChannel",
          "lines": "13-16"
        },
        {
          "file": "src/modules/channel/channel.service.ts",
          "function": "create",
          "lines": "21-24"
        }
      ]
    },
    {
      "feature_description": "實現`在頻道中發送消息`功能",
      "implementation_location": [
        {
          "file": "src/modules/message/message.resolver.ts",
          "function": "createMessage",
          "lines": "13-16"
        },
        {
          "file": "src/modules/message/message.service.ts",
          "function": "create",
          "lines": "23-34"
        }
      ]
    },
    {
      "feature_description": "實現`按時間倒序列出頻道中的消息`功能",
      "implementation_location": [
        {
          "file": "src/modules/message/message.resolver.ts",
          "function": "findAll",
          "lines": "18-21"
        },
        {
          "file": "src/modules/message/message.service.ts",
          "function": "findAll",
          "lines": "41-66"
        }
      ]
    }
  ],
  "execution_plan_suggestion": "要運行此項目，應首先執行 `npm install` 安裝依賴，然後執行 `npm run start:dev` 來啟動服務。該服務是一個GraphQL API，可以在 http://localhost:3000/graphql 訪問。"
}
```

## 加分項 (可選)

**目標：動態驗證功能的正確性。**

在完成核心任務的基礎上，如果你能讓Agent更進一步，**自動驗證**是否能正確工作，並給出**可執行的單元測試**，你將獲得極大的加分。

這通常意味著你的Agent需要具備動態生成和執行測試代碼的能力。

**包含加分項的JSON報告結構示例：**

```json
{
  "feature_analysis": {
    "...": "..."
  },
  "functional_verification": {
    "generated_test_code": "const request = require('supertest');\nconst assert = require('assert');\n\ndescribe('GraphQL API', () => {\n  it('should create a channel and then a message in it', async () => {\n    const server = 'http://localhost:3000';\n    const createChannelQuery = `mutation { createChannel(createChannelInput: { name: \"New Channel\" }) { id, name } }`;\n    const channelRes = await request(server).post('/graphql').send({ query: createChannelQuery });\n    const channelId = channelRes.body.data.createChannel.id;\n\n    const createMessageQuery = `mutation { createMessage(createMessageInput: { channelId: ${channelId}, title: \"Hello\", content: \"World\" }) { id, title } }`;\n    const messageRes = await request(server).post('/graphql').send({ query: createMessageQuery });\n\n    assert.equal(messageRes.body.data.createMessage.title, 'Hello');\n  });\n});",
    "execution_result": {
      "tests_passed": true,
      "log": "1 passing (2s)"
    }
  }
}
```

## 交付要求

1.  **Agent源碼**: 提供你的Agent的完整源代碼的GitHub倉庫地址。請確保代碼結構清晰，並包含必要的說明文檔。
2.  **可執行環境**: 提供一種標准化的方式來運行你的Agent。請在以下兩種方式中**任選其一**：
    *   **選項A (推薦):** 在源碼倉庫中包含一個 `Dockerfile` 及相關說明，使我們能夠通過 `docker build` 和 `docker run` 快速啟動你的Agent服務。
    *   **選項B:** 如果你使用n8n等工作流工具，請提供可直接導入的工作流文件（`.json`格式）及必要的配置說明。

## 評判標准

我們將從以下幾個維度綜合評估你的成果：

*   **任務完成度**: 是否完整、准確地實現了核心任務的要求。
*   **加分項實現**: 是否挑戰並實現了加分項，以及實現的質量。
*   **代碼質量**: 你的Agent源代碼是否結構清晰、易於理解和維護。
*   **設計思路**: 你在Agent設計中（如Prompt Engineering、工作流設計、錯誤處理等）體現的思考深度。

## 評測用的示例數據

在開發和測試過程中，可以使用我們提供的示例項目（example1），也可以自行使用github上的項目進行測試。

