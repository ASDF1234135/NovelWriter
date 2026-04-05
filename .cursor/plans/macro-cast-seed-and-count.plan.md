---
name: ""
overview: ""
todos: []
isProject: false
---

# Macro cast：可選核心角色種子 + 移除 3–5 人上限

## 需求（使用者迭代）

1. **新增結構化欄位**，且 `**macro_author_notes` / `title` / `premise` 等既有自由輸入在未填新欄位時行為不變**（預設空列表 = 與現況相同路徑，僅配合下方規則調整）。
2. **拿掉 cast 人數 3～5 的限制**，改為 **人數不限**，但 prompt 與 normalize 語意上 **每位都必須是貫穿主線的核心人物**（禁止把一次性路人、工具人列入 cast）。

---

## 後端：資料模型與持久化

- 在 `[backend/app/domain/schema.py](backend/app/domain/schema.py)` 新增小型模型，例如：
  - `StoryCastSeedEntry`：`canonical_name: str`（必填）、`role: MacroCastRole | None`（可選，供提示用）、`short_hint: str`（可選，一句話給 macro 參考）。
- `**StoryInput`**：`cast_seed: list[StoryCastSeedEntry] = Field(default_factory=list)`。
- `**StoryPatch**`：可選 `cast_seed: list[StoryCastSeedEntry] | None`（與既有 patch 規則一致：有 workflow 後鎖定等仍由現有邏輯處理）。
- **SQLite**：在 `[database.py](backend/app/repositories/sqlite/database.py)` 以 `_ensure_column` 新增 `cast_seed_json TEXT NOT NULL DEFAULT '[]'`。
- **Repository**：`[story_repository.py](backend/app/repositories/sqlite/story_repository.py)` 的 `create_story` / `patch_story` / `get_story` 讀寫 `cast_seed_json`（與 `cast_json` 區分：`cast_json` 仍為 **macro compile 產出**，`cast_seed` 為 **使用者預先指定的核心名單**）。

---

## Macro compile：提示詞與行為（`[anchor_service.py](backend/app/services/anchor_service.py)`）

- `**_build_macro_prompt`**：把 `story_input.cast_seed` 序列化進送給模型的 JSON（與 `macro_author_notes` 並列）。當 **非空** 時增加硬性說明，例如：
  - 所列 `canonical_name` **不得改名、不得合併、不得遺漏**；
  - 模型需為每位補齊與全書一致的欄位（`short_bio`、`core_motivation`、`notes_links` 等，且仍遵守 `macro_author_notes` 非空時的 KP 規則）。
- **移除** 目前 requirements 中「cast：必須恰好 `MIN_MACRO_CAST`-`MAX_MACRO_CAST` 人」字樣，改為：
  - **人數不限**，但 **僅收核心人物**；禁止過渡性路人、單次工具人進 cast。
  - 保留「1 位 protagonist、0–1 位 antagonist」的結構規則（與現有 `_normalize_cast_output` 角色去重邏輯一致）；若與 `cast_seed` 中多位標成 protagonist 衝突，**仍以 normalize 將多餘改為 supporting**（並可在 prompt 中提醒與 seed 的 role 儘量一致）。

---

## Normalize：`[_normalize_cast_output](backend/app/services/anchor_service.py)`

- **刪除** 依 `MAX_MACRO_CAST` **截斷**列表的邏輯。
- **刪除** `while len(members) < MIN_MACRO_CAST` 用 `_default_cast_drafts` **補滿到 3 人**的迴圈。
- `**cast_seed` 非空時的合併策略**（建議）：
  - 以使用者給的順序為準，對每個 seed 在 LLM 輸出的 `raw` 裡做 **去空白後同名對齊**；
  - 對上的採用模型補全的欄位；對不上的 **用 seed 生成最小 `MacroCastMember`**（`short_bio` 可來自 `short_hint`），避免名單被模型吃掉。
  - 模型在 seed 之外額外回傳的成員：**允許附加**（同樣標為核心人物）；若希望「嚴格等於種子」可另加旗標，本次不列除非你再要求。
- `**cast_seed` 空且 LLM cast 空**：維持現有 `**_default_cast_drafts(story_input)`** 後備，避免圖譜／流程完全無角色（與「保持舊行為可運作」一致）。
- **僅 LLM 有輸出、無 seed**：直接走現有動機補齊、protagonist/antagonist 去重、排序；**不再因人數不足而灌「主要反派／重要配角」**。

常數 `MIN_MACRO_CAST` / `MAX_MACRO_CAST` 可移除或僅保留註解；若有他處引用一併清理。

---

## API 回傳與 Workflow

- `[routes.py](backend/app/api/routes.py)` `get_story_detail` / `patch` 回應中帶上 `cast_seed`（由 row 反序列化），與現有欄位並存。
- `[WorkflowService.macro_compile](backend/app/services/workflow/service.py)` 從 story row 組出 `StoryInput` 時需帶入 `cast_seed`（確認 `get_story` → 建 `StoryInput` 的路徑一致）。

---

## 前端（建議與後端同一變更交付）

- `[frontend/src/types.ts](frontend/src/types.ts)`：`StoryInput` / `StoryPatch` / `StoryDetailResponse` 增加 `cast_seed` 型別。
- `[StorySetupForm.tsx](frontend/src/features/story-setup/StorySetupForm.tsx)`：可選 UI（多列：姓名、可選角色、可選一句提示）；未填則送 `[]`。
- `[App.tsx](frontend/src/app/App.tsx)` `storyDetailToInput`、儲存／建立 story 時傳遞 `cast_seed`。

---

## 測試

- 更新 `[backend/tests/test_anchor_service.py](backend/tests/test_anchor_service.py)`：凡假設 cast 被截斷或補滿 3 人的案例改為新語意。
- 新增案例：`cast_seed` 含固定名、LLM mock 少給一人 → normalize 後仍含該名；LLM 回傳 7 人且不截斷。

---

## 可選防護（實作時斟酌）

- 若擔心極端大 list 拖垮 prompt／DB，可加 **軟上限**（例如 40）並在 API 層驗證；不寫死則需在計畫審查時決定。

---

## Todos

- `schema-repo`: `StoryCastSeedEntry`、`StoryInput`/`StoryPatch` + `cast_seed_json` 欄位與 repository 讀寫
- `anchor-prompt-normalize`: `_build_macro_prompt` 注入 seed + 移除 3～5 文案；`_normalize_cast_output` 合併與移除 min/max 行為
- `workflow-routes`: macro_compile 與 story API 串接 `cast_seed`
- `frontend-cast-seed`: types + 表單 + 儲存
- `tests-anchor`: 調整與新增測試

