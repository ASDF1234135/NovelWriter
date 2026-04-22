// src/features/hitl-panel/HitlPanel.tsx
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo as useMemo2, useState as useState2 } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

// src/api.ts
var API_BASE = "http://localhost:8000/api";
function formatErrorBody(text) {
  if (!text) return "Request failed";
  try {
    const j = JSON.parse(text);
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) {
      return j.detail.map((item) => typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : String(item)).join("; ");
    }
  } catch {
  }
  return text;
}
async function parseJson(response) {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(formatErrorBody(text));
  }
  return response.json();
}
var MACRO_TIMEOUT_MS = 30 * 60 * 1e3;
async function fetchGraph(storyId) {
  const response = await fetch(`${API_BASE}/stories/${storyId}/graph/full`);
  return parseJson(response);
}

// src/i18n/useI18n.ts
import { useContext } from "react";

// src/i18n/I18nProvider.tsx
import { createContext, useCallback, useMemo, useState } from "react";

// src/i18n/locale.ts
var LOCALE_STORAGE_KEY = "nb.ui.locale";
var NAV_MAP = [
  { prefix: "zh-tw", locale: "zh-Hant" },
  { prefix: "zh-hk", locale: "zh-Hant" },
  { prefix: "zh-mo", locale: "zh-Hant" },
  { prefix: "zh-hant", locale: "zh-Hant" },
  { prefix: "zh-cn", locale: "zh-Hans" },
  { prefix: "zh-sg", locale: "zh-Hans" },
  { prefix: "zh-hans", locale: "zh-Hans" },
  { prefix: "en", locale: "en" }
];
function isLocale(value) {
  return value === "zh-Hant" || value === "zh-Hans" || value === "en";
}
function detectLocaleFromNavigator() {
  const lang = String(navigator.language ?? "").trim().toLowerCase();
  for (const row of NAV_MAP) {
    if (lang.startsWith(row.prefix)) return row.locale;
  }
  if (lang.startsWith("zh")) return "zh-Hant";
  return "zh-Hant";
}

// src/i18n/messages.ts
var zhHant = {
  "common.storyLibrary": "\u6545\u4E8B\u5EAB",
  "common.newStory": "\u65B0\u6545\u4E8B",
  "common.settingsAndPlan": "\u8A2D\u5B9A\u8207\u898F\u5283",
  "common.chapterRun": "\u7AE0\u7BC0\u57F7\u884C",
  "common.reviewFix": "\u6AA2\u95B1\u8207\u4FEE\u6B63",
  "common.graph": "\u4E00\u81F4\u6027\u5716\u8B5C",
  "common.export": "\u532F\u51FA",
  "common.currentStory": "\u76EE\u524D\u6545\u4E8B",
  "common.workflowStatus": "\u5DE5\u4F5C\u6D41\u7A0B\u72C0\u614B",
  "common.selectStoryFirst": "\u8ACB\u5148\u5F9E\u6545\u4E8B\u5EAB\u9078\u64C7\u4E00\u5247\u6545\u4E8B",
  "library.subtitle": "\u9078\u64C7\u65E2\u6709\u5C08\u6848\u7E7C\u7E8C\u7DE8\u8F2F\uFF0C\u6216\u958B\u59CB\u4E00\u5247\u65B0\u6545\u4E8B\u3002",
  "library.yourStories": "\u4F60\u7684\u6545\u4E8B",
  "library.loading": "\u8F09\u5165\u4E2D\u2026",
  "library.empty": "\u5C1A\u7121\u6545\u4E8B\u3002\u9EDE\u300C\u65B0\u6545\u4E8B\u300D\u5EFA\u7ACB\u7B2C\u4E00\u500B\u5C08\u6848\u3002",
  "library.targetWords": "\u76EE\u6A19\u5B57\u6578",
  "library.storyId": "\u6545\u4E8B\u7DE8\u865F",
  "library.loadFailed": "\u7121\u6CD5\u8F09\u5165\u6545\u4E8B\u5217\u8868",
  "library.deleteFailed": "\u522A\u9664\u5931\u6557",
  "library.delete": "\u522A\u9664",
  "library.deleteConfirm": "\u78BA\u5B9A\u522A\u9664\u300C{title}\u300D\uFF1F\u6B64\u52D5\u4F5C\u7121\u6CD5\u5FA9\u539F\u3002",
  "setup.items": "\u8A2D\u5B9A\u9805\u76EE",
  "setup.locked": "\u5DF2\u9396\u5B9A\uFF08\u64B0\u5BEB\u672C\u7AE0\u5F8C\u4E0D\u53EF\u4FEE\u6539\uFF09",
  "setup.worldHint": "\u4E16\u754C\u89C0\u7E3D\u8868\u6703\u4F9D\u4F60\u7684\u6545\u4E8B\u6897\u6982\u8207\u88DC\u5145\u7B46\u8A18\uFF0C\u5728\u57F7\u884C\u4E16\u754C\u89C0\u7DE8\u8B6F\u5F8C\u81EA\u52D5\u7522\u751F\uFF1B\u4E00\u822C\u7121\u9700\u624B\u52D5\u7DE8\u8F2F\u7D50\u69CB\u5316\u6A94\u6848\u3002",
  "setup.title": "\u66F8\u540D",
  "setup.targetWords": "\u5168\u66F8\u76EE\u6A19\u5B57\u6578",
  "setup.planRetryLimit": "\u5927\u7DB1\u91CD\u8A66\u6B21\u6578\u4E0A\u9650",
  "setup.draftRetryLimit": "\u5167\u6587\u8207\u95B1\u8B80\u6AA2\u67E5\u91CD\u8A66\u6B21\u6578",
  "setup.outputLanguage": "\u7522\u51FA\u8A9E\u8A00 / Output language",
  "setup.outputLanguageHint": "\u5F71\u97FF\u7AE0\u7BC0\u6B63\u6587\u3001\u5927\u7DB1\u3001\u5BE9\u7A3F\u56DE\u994B\u8207\u5716\u8B5C\u6458\u8981\u7684\u7528\u8A9E\uFF08\u7CFB\u7D71\u6307\u4EE4\u4ECD\u70BA\u82F1\u6587\uFF09\u3002",
  "setup.premise": "\u6545\u4E8B\u6838\u5FC3\uFF0F\u6897\u6982",
  "setup.authorNotes": "\u4F5C\u8005\u88DC\u5145\uFF08\u91CD\u8981\uFF09",
  "setup.authorNotesPlaceholder": "\u4E16\u754C\u89C0\u7D30\u7BC0\u3001\u89D2\u8272\u95DC\u4FC2\u3001\u7981\u5FCC\u3001\u7BC7\u5E45\u7BC0\u594F\u2026\u2026\u683C\u5F0F\u4E0D\u62D8\uFF08Markdown\u3001\u689D\u5217\u7686\u53EF\uFF09\u3002",
  "setup.notesSoftCap": "{count} / ~{max} \u5EFA\u8B70\u4E0A\u9650",
  "setup.notesSoftCapOverflow": "\uFF08\u904E\u9577\u6642\u7CFB\u7D71\u6703\u81EA\u52D5\u622A\u77ED\uFF09",
  "setup.createStory": "\u5EFA\u7ACB\u6545\u4E8B",
  "setup.saveSettings": "\u5132\u5B58\u8A2D\u5B9A",
  "setup.projectFiles": "\u5C08\u6848\u6A94\u6848\uFF08\u91CD\u8981\uFF09",
  "setup.exportProjectJson": "\u532F\u51FA\u5C08\u6848 JSON",
  "setup.importProjectJson": "\u532F\u5165\u5C08\u6848 JSON",
  "setup.importModeConfirm": "\u532F\u5165\u6A21\u5F0F\uFF1A\u6309\u300C\u78BA\u5B9A\u300D= \u8986\u84CB\u76EE\u524D\u8CC7\u6599\uFF1B\u6309\u300C\u53D6\u6D88\u300D= \u5408\u4F75\uFF08\u5DF2\u6709\u503C\u512A\u5148\uFF09",
  "setup.importFailed": "\u532F\u5165\u5C08\u6848 JSON \u5931\u6557",
  "lang.zhHant": "\u7E41\u9AD4\u4E2D\u6587\uFF08Traditional Chinese\uFF09",
  "lang.zhHans": "\u7B80\u4F53\u4E2D\u6587\uFF08Simplified Chinese\uFF09",
  "lang.en": "English",
  "hitl.delete": "\u522A\u9664",
  "hitl.title": "\u9700\u8981\u60A8\u5354\u52A9",
  "hitl.workflowPaused": "\u6D41\u7A0B\u5DF2\u66AB\u505C",
  "hitl.noPending": "\u76EE\u524D\u6C92\u6709\u7B49\u5F85\u60A8\u8655\u7406\u7684\u6B65\u9A5F\u3002",
  "hitl.abortChapter": "\u653E\u68C4\u672C\u7AE0\u8349\u7A3F\uFF0C\u6253\u6389\u91CD\u7DF4",
  "hitl.modeRecommended": "\u5EFA\u8B70\u6A21\u5F0F",
  "hitl.modeExpert": "\u5C08\u5BB6\u6A21\u5F0F",
  "hitl.modeSwitchAria": "HITL \u6A21\u5F0F\u5207\u63DB",
  "hitl.resumeNear": "\u66AB\u505C\u5F8C\u6703\u5F9E\u300C{step}\u300D\u9644\u8FD1\u63A5\u7E8C\uFF08\u4F9D\u60A8\u9078\u64C7\u53EF\u80FD\u8B8A\u66F4\uFF09\u3002",
  "hitl.systemFeedback": "\u7CFB\u7D71\u8AAA\u660E",
  "hitl.quickActions": "\u5FEB\u901F\u8655\u7406",
  "hitl.chooseSolution": "\u9078\u64C7\u505A\u6CD5",
  "hitl.noDedicatedForm": "\u6B64\u66AB\u505C\u6C92\u6709\u5C08\u7528\u8868\u55AE\u3002\u82E5\u4E0A\u65B9\u6709\u5FEB\u901F\u8655\u7406\u8ACB\u512A\u5148\u4F7F\u7528\uFF1B\u5426\u5247\u8ACB\u5C55\u958B\u4E0B\u65B9\u9032\u968E\u9078\u9805\u3002",
  "hitl.chooseSolutionAbove": "\u8ACB\u9078\u64C7\u4E0A\u65B9\u505A\u6CD5\u3002",
  "hitl.advancedSummary": "\u9032\u968E\uFF1A\u50C5\u5728\u719F\u6089\u7CFB\u7D71\u6642\u4F7F\u7528",
  "hitl.reasonCode": "\u5167\u90E8\u539F\u56E0\u78BC",
  "hitl.directMutation": "\u76F4\u63A5\u5BEB\u5165\u6545\u4E8B\u8CC7\u6599\uFF08\u9032\u968E\u7D50\u69CB\u5316\uFF09",
  "hitl.directMutationWarn": "\u932F\u8AA4\u64CD\u4F5C\u53EF\u80FD\u7834\u58DE\u8CC7\u6599\uFF0C\u8ACB\u8B39\u614E\u3002",
  "hitl.directMutationAck": "\u6211\u5DF2\u4E86\u89E3\u6B64\u64CD\u4F5C\u6703\u76F4\u63A5\u8B8A\u66F4\u6545\u4E8B\u5716\u8B5C\u8CC7\u6599\uFF0C\u4E14\u53EF\u80FD\u7121\u6CD5\u9084\u539F\u3002",
  "hitl.writeAndContinue": "\u57F7\u884C\u5BEB\u5165\u4E26\u7E7C\u7E8C",
  "hitl.previewMutationTitle": "\u9001\u51FA\u524D\u9810\u89BD\uFF1A\u76F4\u63A5\u5BEB\u5165\u6545\u4E8B\u8CC7\u6599",
  "hitl.previewMutationBullets": "\u5373\u5C07\u5BEB\u5165 {count} \u7B46 mutation\uFF1B\u6B64\u64CD\u4F5C\u53EF\u80FD\u7121\u6CD5\u9084\u539F\uFF0C\u8ACB\u78BA\u8A8D\u3002",
  "hitl.confirmWrite": "\u78BA\u8A8D\u57F7\u884C\u5BEB\u5165",
  "hitl.backEdit": "\u8FD4\u56DE\u7DE8\u8F2F",
  "hitl.planLoop.headline": "\u5927\u7DB1\u898F\u5283\u89F8\u767C\u5B89\u5168\u9650\u5236\uFF0CAI \u7121\u6CD5\u7522\u51FA\u7B26\u5408\u908F\u8F2F\u7684\u5287\u60C5\u3002",
  "hitl.planLoop.failurePrefix": "\u7121\u6CD5\u901A\u904E\u539F\u56E0",
  "hitl.resolutionTactic.headline": "\u76EE\u524D\u300C{tactic}\u300D\u5DF2\u9023\u7E8C\u591A\u7AE0\u91CD\u8907\u4F7F\u7528\u3002",
  "hitl.resolutionTactic.tacticFallback": "\u6B64\u6536\u5C3E\u5957\u8DEF",
  "hitl.endingVibe.headline": "\u7AE0\u7BC0\u7D50\u5C3E\u7684\u300C{vibe}\u300D\u60C5\u7DD2\u6C23\u6C1B\u91CD\u8907\u904E\u591A\u6B21\uFF0C\u8B80\u8005\u53EF\u80FD\u6703\u75B2\u52DE\u3002",
  "hitl.endingVibe.vibeFallback": "\u76EE\u524D\u6C1B\u570D",
  "hitl.bStoryCooldown.headline": "\u652F\u7DDA\u5287\u60C5\u300C{name}\u300D\u5DF2\u7D93 {n} \u7AE0\u6C92\u6709\u9032\u5C55\uFF0C\u5FC5\u9808\u5728\u9019\u7AE0\u63A8\u9032\u3002",
  "hitl.bStoryCooldown.nameFallback": "\u6B64\u526F\u7DDA",
  "hitl.bStoryCooldown.nFallback": "\u591A",
  "hitl.draftLoop.headline": "AI \u7522\u51FA\u7684\u6B63\u6587\u53CD\u8986\u4FEE\u6539\u4ECD\u672A\u9054\u6A19\uFF08\u5B57\u6578\u4E0D\u8DB3\u6216\u504F\u96E2\u5927\u7DB1\uFF09\u3002",
  "hitl.outputLanguage.headline": "AI \u7522\u51FA\u7684\u8A9E\u8A00\u8207\u5C08\u6848\u8A2D\u5B9A\u4E0D\u7B26\uFF08\u4F8B\u5982\u4E2D\u6587\u6DF7\u96DC\u4E86\u5927\u91CF\u5916\u6587\uFF09\u3002",
  "hitl.extraction.headline": "\u8349\u7A3F\u4E2D\u51FA\u73FE\u7CFB\u7D71\u7121\u6CD5\u8FA8\u8B58\u7684\u65B0\u540D\u8A5E\u6216\u89D2\u8272\uFF0C\u5716\u8B5C\u5165\u5EAB\u5931\u6557\u3002",
  "hitl.extraction.entitiesPrefix": "\u76F8\u95DC\uFF1A{names}",
  "hitl.bStoryResolve.headline": "AI \u731C\u6E2C\u652F\u7DDA\u300C{name}\u300D\u53EF\u80FD\u5DF2\u7D93\u5B8C\u7D50\uFF0C\u8ACB\u9032\u884C\u6700\u7D42\u88C1\u6C7A\u3002",
  "hitl.bStoryResolve.nameFallback": "\u6B64\u652F\u7DDA",
  "hitl.context.headline": "\u6545\u4E8B\u7684\u53C3\u8003\u8A18\u61B6\u9AD4\u5373\u5C07\u585E\u6EFF\uFF0C\u9700\u8981\u6E05\u7406\u9673\u5E74\u820A\u4E8B\u4EE5\u4FDD\u6301 AI \u6548\u80FD\u3002",
  "hitl.context.estimate": "\u76EE\u524D\u4F30\u7B97\u53C3\u8003\u5167\u5BB9\u7D04 {n} \u5B57\uFF0C\u8ACB\u8996\u60C5\u6CC1\u522A\u6E1B\u3002",
  "hitl.alignment.headline": "\u7CFB\u7D71\u9047\u5230\u300C{issue}\u300D\uFF0C\u9700\u8981\u660E\u78BA\u7684\u6307\u5C0E\u65B9\u91DD\u8207\u4EBA\u985E\u5275\u610F\u4ECB\u5165\u3002",
  "hitl.alignment.issueFallback": "\u8907\u96DC\u5C0D\u9F4A\u554F\u984C",
  "hitl.alignment.placeholder": "\u8ACB\u8F38\u5165\u4F60\u7684\u5EFA\u8B70\uFF1B\u7559\u7A7A\u8B93 AI \u81EA\u7531\u5275\u4F5C\uFF08\u4E0D\u5EFA\u8B70\uFF09\u3002",
  "hitl.alignment.submit": "\u9001\u51FA\u4E26\u7E7C\u7E8C",
  "hitl.alignment.required": "\u8ACB\u586B\u5BEB\u5EFA\u8B70\u5F8C\u518D\u7E7C\u7E8C\u3002",
  "hitl.outputLanguage.projectLang": "\u5C08\u6848\u8F38\u51FA\u8A9E\u8A00\uFF1A",
  "hitl.option.allow_adjust_anchor": "\u5141\u8A31\u5EF6\u5F8C\u672A\u4F86\u76EE\u6A19",
  "hitl.option.force_approve_plan": "\u4E00\u9375\u653E\u884C\uFF08\u5F37\u5236\u901A\u904E\uFF09",
  "hitl.option.force_rewrite_plan": "\u6574\u7D44\u9000\u56DE\u91CD\u4F5C",
  "hitl.option.keep_current_logic": "\u7DAD\u6301\u73FE\u6709\u8349\u7A3F\uFF08\u5F37\u5236\u901A\u904E\uFF09",
  "hitl.option.relax_word_count": "\u653E\u5BEC\u5B57\u6578\u9650\u5236",
  "hitl.option.extraction_return_author": "\u6253\u56DE\u7D66 AI \u91CD\u5BEB\uFF08\u53EB\u5B83\u5BEB\u5C0D\u540D\u5B57\uFF09",
  "hitl.option.language_return_author": "\u6253\u56DE\u91CD\u5BEB",
  "hitl.option.language_force_continue": "\u5F37\u5236\u7E7C\u7E8C\uFF08\u9019\u662F\u6211\u6545\u610F\u7684\uFF09",
  "hitl.hint.allow_adjust_anchor": "\u9001\u51FA\u5F8C\u53EF\u65BC\u4E0B\u65B9\u586B\u5BEB\u300C\u5EF6\u5F8C\u91CC\u7A0B\u7891\u300D\u6307\u5B9A\u6539\u5230\u54EA\u4E00\u7AE0\u3002",
  "hitl.hint.force_rewrite_plan": "\u6E05\u7A7A\u5927\u7DB1\u91CD\u8A66\u8A08\u6B21\uFF0C\u4E26\u4EE5\u4F60\u7DE8\u8F2F\u5F8C\u7684\u5927\u7DB1\u91CD\u65B0\u898F\u5283\u3002",
  "hitl.hint.force_approve_plan": "\u63A5\u53D7\u76EE\u524D\u5927\u7DB1\u4E26\u9032\u5165\u64B0\u5BEB\uFF08\u8ACB\u81EA\u8CA0\u5F8C\u7E8C\u98A8\u96AA\uFF09\u3002",
  "hitl.hint.keep_current_logic": "\u7DAD\u6301\u5287\u60C5\u908F\u8F2F\u4E26\u91CD\u7F6E\u91CD\u8A66\u6B21\u6578\uFF0C\u8ACB\u63A5\u8457\u4FEE\u6539\u6B63\u6587\u3002",
  "hitl.hint.relax_word_count": "\u653E\u5BEC\u5B57\u6578\u76EE\u6A19\u7D04\u56DB\u6210\uFF0C\u8B93\u5BE9\u6838\u8F03\u6613\u901A\u904E\u3002",
  "hitl.hint.extraction_return_author": "\u5148\u56DE\u5230\u64B0\u5BEB\u968E\u6BB5\uFF0C\u4FEE\u6B63\u6587\u4E2D\u7528\u8A5E\u8207\u6307\u6D89\u3002",
  "hitl.hint.language_return_author": "\u56DE\u5230\u64B0\u5BEB\uFF0C\u4F9D\u5C08\u6848\u8F38\u51FA\u8A9E\u8A00\u91CD\u5BEB\u672C\u7AE0\u6B63\u6587\u3002",
  "hitl.hint.language_force_continue": "\u63A5\u53D7\u76EE\u524D\u6B63\u6587\u4E26\u7565\u904E\u8A9E\u8A00\u6AA2\u67E5\uFF0C\u7E7C\u7E8C\u5F59\u7E3D\u3002",
  "hitl.outline.title": "\u4E8B\u4EF6\u5927\u7DB1",
  "hitl.outline.hint": "\u9EDE\u5361\u7247\u5167\u6587\u5B57\u5373\u53EF\u4FEE\u6539\uFF1B\u53EF\u62D6\u66F3\u6392\u5E8F\u3002",
  "hitl.outline.eventN": "\u4E8B\u4EF6 {n}",
  "hitl.outline.eventId": "\u4E8B\u4EF6\u4EE3\u865F",
  "hitl.outline.description": "\u4E8B\u4EF6\u5167\u5BB9\uFF08\u7D14\u6587\u5B57\uFF09",
  "hitl.outline.causedBy": "\u56E0\u679C\u524D\u5E8F\uFF08\u53EF\u7A7A\uFF09",
  "hitl.outline.addCard": "\u65B0\u589E\u4E8B\u4EF6\u5361\u7247",
  "hitl.outline.narrativeScript": "\u8868\u5C64\u6558\u4E8B\u8173\u672C\uFF08\u9078\u586B\uFF09",
  "hitl.outline.previewTitle": "\u9001\u51FA\u524D\u9810\u89BD\uFF1A\u4E8B\u4EF6\u5927\u7DB1\u8B8A\u66F4",
  "hitl.outline.previewConfirm": "\u78BA\u8A8D\u5957\u7528\u5927\u7DB1",
  "hitl.outline.previewApply": "\u9810\u89BD\u4E26\u5957\u7528\u5927\u7DB1",
  "hitl.outline.previewStats": "\u65B0\u589E {added} \u7B46 \xB7 \u522A\u9664 {removed} \u7B46 \xB7 \u5171 {total} \u7B46\u4E8B\u4EF6",
  "hitl.director.titlePlan": "\u7D66 AI \u7684\u5C0E\u6F14\u7B46\u8A18",
  "hitl.director.titleBStory": "\u544A\u8A34 AI \u9019\u7AE0\u8981\u600E\u9EBC\u767C\u5C55\u9019\u689D\u526F\u7DDA\uFF1F",
  "hitl.director.placeholder": "\u7C21\u77ED\u8AAA\u660E\u672C\u7AE0\u65B9\u5411\u3001\u7BC0\u594F\u6216\u7981\u5FCC\u2026",
  "hitl.director.apply": "\u5957\u7528\u4E26\u7E7C\u7E8C",
  "hitl.anchor.sectionTitle": "\u5EF6\u5F8C\u91CC\u7A0B\u7891\uFF08\u9078\u586B\uFF09",
  "hitl.anchor.hint": "\u82E5\u9700\u628A\u67D0\u500B\u6545\u4E8B\u7BC0\u9EDE\u6539\u5230\u8F03\u665A\u7684\u7AE0\u518D\u9054\u6210\uFF0C\u8ACB\u586B\u5BEB\u5F8C\u9001\u51FA\uFF08\u4E0D\u9700\u5148\u9EDE\u4E0A\u65B9\u300C\u5141\u8A31\u5EF6\u5F8C\u300D\u4E5F\u53EF\u9001\u51FA\uFF09\u3002",
  "hitl.anchor.id": "\u91CC\u7A0B\u7891\u4EE3\u865F",
  "hitl.anchor.chapter": "\u6539\u5230\u7B2C\u5E7E\u7AE0",
  "hitl.anchor.submit": "\u5957\u7528\u5EF6\u671F\u4E26\u56DE\u5230\u5287\u60C5\u898F\u5283",
  "hitl.draft.title": "\u4FEE\u6539\u7AE0\u7BC0\u6B63\u6587",
  "hitl.draft.hint": "\u5C08\u540D\u5C0D\u7167\u7DDA\u7D22\u8ACB\u5728\u4E0B\u6B21\u300C\u958B\u59CB\u64B0\u5BEB\u672C\u7AE0\u300D\u6642\u65BC\u7AE0\u7BC0\u8ACB\u6C42\u4E00\u4F75\u9001\u51FA\u3002",
  "hitl.draft.mergeHints": "\u4FDD\u7559\u5DF2\u8490\u96C6\u7684\u5C08\u540D\u7DDA\u7D22",
  "hitl.draft.resumeLabel": "\u9700\u518D\u6B21\u6AA2\u67E5\u55CE\uFF1F",
  "hitl.draft.resume.reader": "\u5F9E\u95B1\u8B80\u6AA2\u67E5\u518D\u8DD1",
  "hitl.draft.resume.draft_supervisor": "\u5F9E\u5167\u6587\u5BE9\u6838\u518D\u8DD1",
  "hitl.draft.resume.author": "\u5F9E\u64B0\u5BEB\u518D\u8DD1",
  "hitl.draft.submit": "\u63D0\u4EA4\u6B63\u6587\u4E26\u7E7C\u7E8C",
  "hitl.remap.title": "\u540D\u8A5E\u9023\u9023\u770B",
  "hitl.remap.hint": "\u5DE6\u5074\u70BA\u8349\u7A3F\u4E2D\u7684\u4E0D\u660E\u7BC0\u9EDE\uFF0C\u53F3\u5074\u8ACB\u9078\u64C7\u5716\u8B5C\u4E2D\u540C\u985E\u578B\u7684\u65E2\u6709\u7BC0\u9EDE\u3002",
  "hitl.remap.leftPlaceholder": "\u9078\u64C7\u4E0D\u660E\u540D\u8A5E",
  "hitl.remap.rightPlaceholder": "\u9078\u64C7\u5716\u8B5C\u5C0D\u61C9",
  "hitl.remap.addRow": "\u65B0\u589E\u5C0D\u7167\u5217",
  "hitl.remap.previewTitle": "\u9001\u51FA\u524D\u9810\u89BD\uFF1A\u5C0D\u7167",
  "hitl.remap.previewConfirm": "\u78BA\u8A8D\u5957\u7528\u5C0D\u7167",
  "hitl.remap.previewApply": "\u9810\u89BD\u4E26\u5957\u7528\u5C0D\u7167",
  "hitl.remap.noHints": "\u76EE\u524D\u6C92\u6709\u7CFB\u7D71\u731C\u6E2C\u8868\uFF0C\u8ACB\u4F9D\u5167\u6587\u81EA\u884C\u5C0D\u7167\u3002",
  "hitl.remap.waiveAdvanced": "\u53EF\u7565\u904E\u7684\u5FC5\u586B\u9805\uFF08\u9017\u865F\uFF0C\u9032\u968E\uFF09",
  "hitl.remap.graphLoading": "\u6B63\u5728\u8F09\u5165\u5716\u8B5C\u2026",
  "hitl.remap.graphEmpty": "\u5C1A\u7121\u5716\u8B5C\u8CC7\u6599\uFF0C\u8ACB\u7A0D\u5F8C\u6216\u81F3\u5716\u8B5C\u9801\u91CD\u65B0\u6574\u7406\u3002",
  "hitl.bStory.sectionTitle": "\u526F\u7DDA\u6536\u5C3E\u5224\u5B9A",
  "hitl.bStory.notesExpert": "\u88DC\u5145\u8AAA\u660E\uFF08\u7D50\u6848\u5206\u6790\uFF0C\u6703\u4E00\u4F75\u5B58\u6A94\uFF09",
  "hitl.bStory.resolvedIds": "\u8996\u70BA\u5DF2\u6536\u5C3E\u7684\u526F\u7DDA\u4EE3\u865F",
  "hitl.bStory.evidenceIds": "\u7576\u4F5C\u8B49\u64DA\u7684\u60C5\u7BC0\u4E8B\u4EF6\u4EE3\u865F",
  "hitl.bStory.rejectSubmit": "\u78BA\u8A8D\u6253\u56DE\u4E26\u56DE\u5230\u6240\u9078\u6B65\u9A5F",
  "hitl.bStory.rejectCancel": "\u53D6\u6D88\uFF0C\u6539\u70BA\u7D50\u6848",
  "hitl.bStory.yes": "\u6C92\u932F\uFF0C\u9019\u689D\u7DDA\u5DF2\u6B63\u5F0F\u5B8C\u7D50",
  "hitl.bStory.no": "\u9084\u6C92\u7D50\u675F\uFF0C\u7E7C\u7E8C\u767C\u5C55",
  "hitl.bStory.noExpandLabel": "\u9084\u7F3A\u4E86\u4EC0\u9EBC\u5287\u60C5\uFF1F\uFF08\u9078\u586B\uFF09",
  "hitl.bStory.rejectResume": "\u6253\u56DE\u5F8C\u5F9E\u54EA\u4E00\u6B65\u91CD\u4F86",
  "hitl.bStory.resumeOption.extraction_gate": "\u8A2D\u5B9A\u6B78\u6A94",
  "hitl.bStory.resumeOption.author": "\u64B0\u5BEB\u5167\u6587",
  "hitl.bStory.resumeOption.b_story_resolve": "\u526F\u7DDA\u6536\u5C3E",
  "hitl.prune.title": "\u6E05\u7406\u53C3\u8003\u8A18\u61B6",
  "hitl.prune.hint": "\u9078\u64C7\u7CBE\u7C21\u7A0B\u5EA6\uFF1A\u6578\u5B57\u6108\u5927\uFF0C\u6108\u591A\u820A\u7D30\u7BC0\u6703\u88AB\u7E2E\u6E1B\u3002",
  "hitl.prune.tier0": "0\uFF1A\u76E1\u91CF\u4FDD\u7559\u7D30\u7BC0",
  "hitl.prune.tier1": "1\uFF1A\u4E2D\u5EA6\u522A\u6E1B\u820A\u5287\u60C5",
  "hitl.prune.tier2": "2\uFF1A\u7A4D\u6975\u5931\u61B6\uFF08\u50C5\u4FDD\u7559\u5927\u4E3B\u7DDA\uFF09",
  "hitl.prune.apply": "\u5957\u7528\u4E26\u91CD\u65B0\u6574\u7406\u80CC\u666F",
  "hitl.preview.forceApproveTitle": "\u9001\u51FA\u524D\u9810\u89BD\uFF1A\u5F37\u5236\u901A\u904E\u5927\u7DB1",
  "hitl.preview.forceApproveBullet1": "\u5C07\u76F4\u63A5\u4EE5\u76EE\u524D\u5927\u7DB1\u9032\u5165\u64B0\u5BEB\u3002",
  "hitl.preview.forceApproveBullet2": "\u5F8C\u7E8C\u82E5\u908F\u8F2F\u4E0D\u8DB3\uFF0C\u53EF\u80FD\u589E\u52A0\u8349\u7A3F\u91CD\u5BEB\u6210\u672C\u3002",
  "hitl.preview.forceApproveConfirm": "\u78BA\u8A8D\u5F37\u5236\u901A\u904E"
};
var zhHans = {
  ...zhHant,
  "common.storyLibrary": "\u6545\u4E8B\u5E93",
  "common.newStory": "\u65B0\u6545\u4E8B",
  "common.settingsAndPlan": "\u8BBE\u7F6E\u4E0E\u89C4\u5212",
  "common.chapterRun": "\u7AE0\u8282\u6267\u884C",
  "common.reviewFix": "\u68C0\u9605\u4E0E\u4FEE\u6B63",
  "common.graph": "\u4E00\u81F4\u6027\u56FE\u8C31",
  "common.export": "\u5BFC\u51FA",
  "common.currentStory": "\u5F53\u524D\u6545\u4E8B",
  "common.workflowStatus": "\u5DE5\u4F5C\u6D41\u72B6\u6001",
  "common.selectStoryFirst": "\u8BF7\u5148\u4ECE\u6545\u4E8B\u5E93\u9009\u62E9\u4E00\u4E2A\u6545\u4E8B",
  "library.yourStories": "\u4F60\u7684\u6545\u4E8B",
  "library.subtitle": "\u9009\u62E9\u5DF2\u6709\u9879\u76EE\u7EE7\u7EED\u7F16\u8F91\uFF0C\u6216\u5F00\u59CB\u4E00\u4E2A\u65B0\u6545\u4E8B\u3002",
  "library.empty": "\u6682\u65E0\u6545\u4E8B\u3002\u70B9\u51FB\u201C\u65B0\u6545\u4E8B\u201D\u5EFA\u7ACB\u7B2C\u4E00\u4E2A\u9879\u76EE\u3002",
  "library.targetWords": "\u76EE\u6807\u5B57\u6570",
  "library.storyId": "\u6545\u4E8B\u7F16\u53F7",
  "library.loadFailed": "\u65E0\u6CD5\u52A0\u8F7D\u6545\u4E8B\u5217\u8868",
  "library.deleteFailed": "\u5220\u9664\u5931\u8D25",
  "library.deleteConfirm": "\u786E\u5B9A\u5220\u9664\u201C{title}\u201D\uFF1F\u6B64\u64CD\u4F5C\u65E0\u6CD5\u6062\u590D\u3002",
  "setup.items": "\u8BBE\u7F6E\u9879",
  "setup.locked": "\u5DF2\u9501\u5B9A\uFF08\u64B0\u5199\u672C\u7AE0\u540E\u4E0D\u53EF\u4FEE\u6539\uFF09",
  "setup.worldHint": "\u4E16\u754C\u89C2\u603B\u8868\u4F1A\u4F9D\u636E\u6545\u4E8B\u6897\u6982\u4E0E\u8865\u5145\u7B14\u8BB0\uFF0C\u5728\u6267\u884C\u4E16\u754C\u89C2\u7F16\u8BD1\u540E\u81EA\u52A8\u751F\u6210\uFF1B\u901A\u5E38\u65E0\u9700\u624B\u52A8\u7F16\u8F91\u7ED3\u6784\u5316\u6587\u4EF6\u3002",
  "setup.title": "\u4E66\u540D",
  "setup.targetWords": "\u5168\u4E66\u76EE\u6807\u5B57\u6570",
  "setup.planRetryLimit": "\u5927\u7EB2\u91CD\u8BD5\u6B21\u6570\u4E0A\u9650",
  "setup.draftRetryLimit": "\u6B63\u6587\u4E0E\u9605\u8BFB\u68C0\u67E5\u91CD\u8BD5\u6B21\u6570",
  "setup.outputLanguageHint": "\u5F71\u54CD\u7AE0\u8282\u6B63\u6587\u3001\u5927\u7EB2\u3001\u5BA1\u7A3F\u53CD\u9988\u4E0E\u56FE\u8C31\u6458\u8981\u7684\u7528\u8BED\uFF08\u7CFB\u7EDF\u6307\u4EE4\u4ECD\u4E3A\u82F1\u6587\uFF09\u3002",
  "setup.premise": "\u6545\u4E8B\u6838\u5FC3/\u6897\u6982",
  "setup.authorNotes": "\u4F5C\u8005\u8865\u5145\uFF08\u91CD\u8981\uFF09",
  "setup.authorNotesPlaceholder": "\u4E16\u754C\u89C2\u7EC6\u8282\u3001\u89D2\u8272\u5173\u7CFB\u3001\u7981\u5FCC\u3001\u7BC7\u5E45\u8282\u594F\u2026\u2026\u683C\u5F0F\u4E0D\u9650\uFF08Markdown\u3001\u5217\u8868\u5747\u53EF\uFF09\u3002",
  "setup.notesSoftCapOverflow": "\uFF08\u8FC7\u957F\u65F6\u7CFB\u7EDF\u4F1A\u81EA\u52A8\u622A\u65AD\uFF09",
  "setup.createStory": "\u521B\u5EFA\u6545\u4E8B",
  "setup.saveSettings": "\u4FDD\u5B58\u8BBE\u7F6E",
  "setup.projectFiles": "\u9879\u76EE\u6587\u4EF6\uFF08\u91CD\u8981\uFF09",
  "setup.exportProjectJson": "\u5BFC\u51FA\u9879\u76EE JSON",
  "setup.importProjectJson": "\u5BFC\u5165\u9879\u76EE JSON",
  "setup.importModeConfirm": "\u5BFC\u5165\u6A21\u5F0F\uFF1A\u6309\u201C\u786E\u5B9A\u201D= \u8986\u76D6\u5F53\u524D\u6570\u636E\uFF1B\u6309\u201C\u53D6\u6D88\u201D= \u5408\u5E76\uFF08\u5DF2\u6709\u503C\u4F18\u5148\uFF09",
  "setup.importFailed": "\u5BFC\u5165\u9879\u76EE JSON \u5931\u8D25",
  "hitl.delete": "\u5220\u9664",
  "hitl.title": "\u9700\u8981\u4F60\u534F\u52A9",
  "hitl.noPending": "\u76EE\u524D\u6CA1\u6709\u7B49\u5F85\u4F60\u5904\u7406\u7684\u6B65\u9AA4\u3002",
  "hitl.abortChapter": "\u653E\u5F03\u672C\u7AE0\u8349\u7A3F\u5E76\u91CD\u8DD1",
  "hitl.modeRecommended": "\u5EFA\u8BAE\u6A21\u5F0F",
  "hitl.modeExpert": "\u4E13\u5BB6\u6A21\u5F0F",
  "hitl.modeSwitchAria": "HITL \u6A21\u5F0F\u5207\u6362",
  "hitl.resumeNear": "\u6682\u505C\u540E\u4F1A\u4ECE\u300C{step}\u300D\u9644\u8FD1\u63A5\u7EED\uFF08\u4F1A\u968F\u4F60\u7684\u9009\u62E9\u6539\u53D8\uFF09\u3002",
  "hitl.systemFeedback": "\u7CFB\u7EDF\u8BF4\u660E",
  "hitl.quickActions": "\u5FEB\u901F\u5904\u7406",
  "hitl.chooseSolution": "\u9009\u62E9\u505A\u6CD5",
  "hitl.noDedicatedForm": "\u6B64\u6682\u505C\u6CA1\u6709\u4E13\u7528\u8868\u5355\u3002\u82E5\u4E0A\u65B9\u6709\u5FEB\u901F\u5904\u7406\u8BF7\u4F18\u5148\u4F7F\u7528\uFF1B\u5426\u5219\u8BF7\u5C55\u5F00\u4E0B\u65B9\u8FDB\u9636\u9009\u9879\u3002",
  "hitl.chooseSolutionAbove": "\u8BF7\u9009\u62E9\u4E0A\u65B9\u505A\u6CD5\u3002",
  "hitl.advancedSummary": "\u8FDB\u9636\uFF1A\u4EC5\u5728\u719F\u6089\u7CFB\u7EDF\u65F6\u4F7F\u7528",
  "hitl.reasonCode": "\u5185\u90E8\u539F\u56E0\u7801",
  "hitl.directMutation": "\u76F4\u63A5\u5199\u5165\u6545\u4E8B\u8D44\u6599\uFF08\u8FDB\u9636\u7ED3\u6784\u5316\uFF09",
  "hitl.directMutationWarn": "\u9519\u8BEF\u64CD\u4F5C\u53EF\u80FD\u7834\u574F\u8D44\u6599\uFF0C\u8BF7\u8C28\u614E\u3002",
  "hitl.directMutationAck": "\u6211\u5DF2\u4E86\u89E3\u6B64\u64CD\u4F5C\u4F1A\u76F4\u63A5\u53D8\u66F4\u6545\u4E8B\u56FE\u8C31\u8D44\u6599\uFF0C\u4E14\u53EF\u80FD\u65E0\u6CD5\u8FD8\u539F\u3002",
  "hitl.writeAndContinue": "\u6267\u884C\u5199\u5165\u5E76\u7EE7\u7EED",
  "hitl.previewMutationTitle": "\u63D0\u4EA4\u524D\u9884\u89C8\uFF1A\u76F4\u63A5\u5199\u5165\u6545\u4E8B\u8D44\u6599",
  "hitl.previewMutationBullets": "\u5373\u5C06\u5199\u5165 {count} \u6761 mutation\uFF1B\u6B64\u64CD\u4F5C\u53EF\u80FD\u65E0\u6CD5\u8FD8\u539F\uFF0C\u8BF7\u786E\u8BA4\u3002",
  "hitl.confirmWrite": "\u786E\u8BA4\u6267\u884C\u5199\u5165",
  "hitl.backEdit": "\u8FD4\u56DE\u7F16\u8F91",
  "hitl.planLoop.headline": "\u5927\u7EB2\u89C4\u5212\u89E6\u53D1\u5B89\u5168\u9650\u5236\uFF0CAI \u65E0\u6CD5\u4EA7\u51FA\u7B26\u5408\u903B\u8F91\u7684\u5267\u60C5\u3002",
  "hitl.planLoop.failurePrefix": "\u65E0\u6CD5\u901A\u8FC7\u539F\u56E0",
  "hitl.resolutionTactic.headline": "\u76EE\u524D\u300C{tactic}\u300D\u5DF2\u8FDE\u7EED\u591A\u7AE0\u91CD\u590D\u4F7F\u7528\u3002",
  "hitl.resolutionTactic.tacticFallback": "\u6B64\u6536\u5C3E\u5957\u8DEF",
  "hitl.endingVibe.headline": "\u7AE0\u8282\u7ED3\u5C3E\u7684\u300C{vibe}\u300D\u60C5\u7EEA\u6C14\u6C1B\u91CD\u590D\u8FC7\u591A\u6B21\uFF0C\u8BFB\u8005\u53EF\u80FD\u4F1A\u75B2\u52B3\u3002",
  "hitl.endingVibe.vibeFallback": "\u76EE\u524D\u6C1B\u56F4",
  "hitl.bStoryCooldown.headline": "\u652F\u7EBF\u5267\u60C5\u300C{name}\u300D\u5DF2\u7ECF {n} \u7AE0\u6CA1\u6709\u8FDB\u5C55\uFF0C\u5FC5\u987B\u5728\u672C\u7AE0\u63A8\u8FDB\u3002",
  "hitl.bStoryCooldown.nameFallback": "\u6B64\u526F\u7EBF",
  "hitl.draftLoop.headline": "AI \u4EA7\u51FA\u7684\u6B63\u6587\u53CD\u590D\u4FEE\u6539\u4ECD\u672A\u8FBE\u6807\uFF08\u5B57\u6570\u4E0D\u8DB3\u6216\u504F\u79BB\u5927\u7EB2\uFF09\u3002",
  "hitl.outputLanguage.headline": "AI \u4EA7\u51FA\u7684\u8BED\u8A00\u4E0E\u9879\u76EE\u8BBE\u5B9A\u4E0D\u7B26\uFF08\u4F8B\u5982\u4E2D\u6587\u6DF7\u6742\u4E86\u5927\u91CF\u5916\u6587\uFF09\u3002",
  "hitl.extraction.headline": "\u8349\u7A3F\u4E2D\u51FA\u73B0\u7CFB\u7EDF\u65E0\u6CD5\u8FA8\u8BC6\u7684\u65B0\u540D\u8BCD\u6216\u89D2\u8272\uFF0C\u56FE\u8C31\u5165\u5E93\u5931\u8D25\u3002",
  "hitl.extraction.entitiesPrefix": "\u76F8\u5173\uFF1A{names}",
  "hitl.bStoryResolve.headline": "AI \u731C\u6D4B\u652F\u7EBF\u300C{name}\u300D\u53EF\u80FD\u5DF2\u7ECF\u7ED3\u675F\uFF0C\u8BF7\u8FDB\u884C\u6700\u7EC8\u88C1\u51B3\u3002",
  "hitl.bStoryResolve.nameFallback": "\u6B64\u652F\u7EBF",
  "hitl.context.headline": "\u6545\u4E8B\u7684\u53C2\u8003\u8BB0\u5FC6\u4F53\u5373\u5C06\u585E\u6EE1\uFF0C\u9700\u8981\u6E05\u7406\u9648\u5E74\u65E7\u4E8B\u4EE5\u4FDD\u6301 AI \u6548\u80FD\u3002",
  "hitl.context.estimate": "\u5F53\u524D\u4F30\u7B97\u53C2\u8003\u5185\u5BB9\u7EA6 {n} \u5B57\uFF0C\u8BF7\u6309\u9700\u5220\u51CF\u3002",
  "hitl.alignment.headline": "\u7CFB\u7EDF\u9047\u5230\u300C{issue}\u300D\uFF0C\u9700\u8981\u660E\u786E\u7684\u6307\u5BFC\u65B9\u9488\u4E0E\u4EBA\u7C7B\u521B\u610F\u4ECB\u5165\u3002",
  "hitl.alignment.issueFallback": "\u590D\u6742\u5BF9\u9F50\u95EE\u9898",
  "hitl.alignment.placeholder": "\u8BF7\u8F93\u5165\u4F60\u7684\u5EFA\u8BAE\uFF1B\u7559\u7A7A\u8BA9 AI \u81EA\u7531\u521B\u4F5C\uFF08\u4E0D\u5EFA\u8BAE\uFF09\u3002",
  "hitl.alignment.submit": "\u9001\u51FA\u5E76\u7EE7\u7EED",
  "hitl.alignment.required": "\u8BF7\u586B\u5199\u5EFA\u8BAE\u540E\u518D\u7EE7\u7EED\u3002",
  "hitl.outputLanguage.projectLang": "\u9879\u76EE\u8F93\u51FA\u8BED\u8A00\uFF1A",
  "hitl.option.allow_adjust_anchor": "\u5141\u8BB8\u5EF6\u540E\u672A\u6765\u76EE\u6807",
  "hitl.option.force_approve_plan": "\u4E00\u952E\u653E\u884C\uFF08\u5F3A\u5236\u901A\u8FC7\uFF09",
  "hitl.option.force_rewrite_plan": "\u6574\u7EC4\u9000\u56DE\u91CD\u505A",
  "hitl.option.keep_current_logic": "\u7EF4\u6301\u73B0\u6709\u8349\u7A3F\uFF08\u5F3A\u5236\u901A\u8FC7\uFF09",
  "hitl.option.relax_word_count": "\u653E\u5BBD\u5B57\u6570\u9650\u5236",
  "hitl.option.extraction_return_author": "\u6253\u56DE\u7ED9 AI \u91CD\u5199\uFF08\u53EB\u5B83\u5199\u5BF9\u540D\u5B57\uFF09",
  "hitl.option.language_return_author": "\u6253\u56DE\u91CD\u5199",
  "hitl.option.language_force_continue": "\u5F3A\u5236\u7EE7\u7EED\uFF08\u8FD9\u662F\u6211\u6545\u610F\u7684\uFF09",
  "hitl.hint.allow_adjust_anchor": "\u9001\u51FA\u540E\u53EF\u5728\u4E0B\u65B9\u586B\u5199\u300C\u5EF6\u540E\u91CC\u7A0B\u7891\u300D\u6307\u5B9A\u6539\u5230\u54EA\u4E00\u7AE0\u3002",
  "hitl.hint.force_rewrite_plan": "\u6E05\u7A7A\u5927\u7EB2\u91CD\u8BD5\u8BA1\u6B21\uFF0C\u5E76\u4EE5\u4F60\u7F16\u8F91\u540E\u7684\u5927\u7EB2\u91CD\u65B0\u89C4\u5212\u3002",
  "hitl.hint.force_approve_plan": "\u63A5\u53D7\u5F53\u524D\u5927\u7EB2\u5E76\u8FDB\u5165\u64B0\u5199\uFF08\u8BF7\u81EA\u8D1F\u540E\u7EED\u98CE\u9669\uFF09\u3002",
  "hitl.hint.keep_current_logic": "\u7EF4\u6301\u5267\u60C5\u903B\u8F91\u5E76\u91CD\u7F6E\u91CD\u8BD5\u6B21\u6570\uFF0C\u8BF7\u63A5\u7740\u4FEE\u6539\u6B63\u6587\u3002",
  "hitl.hint.relax_word_count": "\u653E\u5BBD\u5B57\u6570\u76EE\u6807\u7EA6\u56DB\u6210\uFF0C\u8BA9\u5BA1\u6838\u8F83\u6613\u901A\u8FC7\u3002",
  "hitl.hint.extraction_return_author": "\u5148\u56DE\u5230\u64B0\u5199\u9636\u6BB5\uFF0C\u4FEE\u6B63\u6587\u4E2D\u7528\u8BCD\u4E0E\u6307\u6D89\u3002",
  "hitl.hint.language_return_author": "\u56DE\u5230\u64B0\u5199\uFF0C\u6309\u9879\u76EE\u8F93\u51FA\u8BED\u8A00\u91CD\u5199\u672C\u7AE0\u6B63\u6587\u3002",
  "hitl.hint.language_force_continue": "\u63A5\u53D7\u5F53\u524D\u6B63\u6587\u5E76\u7565\u8FC7\u8BED\u8A00\u68C0\u67E5\uFF0C\u7EE7\u7EED\u6C47\u603B\u3002",
  "hitl.outline.title": "\u4E8B\u4EF6\u5927\u7EB2",
  "hitl.outline.hint": "\u70B9\u51FB\u5361\u7247\u5185\u6587\u5B57\u5373\u53EF\u4FEE\u6539\uFF1B\u53EF\u62D6\u62FD\u6392\u5E8F\u3002",
  "hitl.outline.eventId": "\u4E8B\u4EF6\u4EE3\u53F7",
  "hitl.outline.description": "\u4E8B\u4EF6\u5185\u5BB9\uFF08\u7EAF\u6587\u5B57\uFF09",
  "hitl.outline.causedBy": "\u56E0\u679C\u524D\u5E8F\uFF08\u53EF\u7A7A\uFF09",
  "hitl.outline.addCard": "\u65B0\u589E\u4E8B\u4EF6\u5361\u7247",
  "hitl.outline.narrativeScript": "\u8868\u5C42\u53D9\u4E8B\u811A\u672C\uFF08\u9009\u586B\uFF09",
  "hitl.outline.previewTitle": "\u63D0\u4EA4\u524D\u9884\u89C8\uFF1A\u4E8B\u4EF6\u5927\u7EB2\u53D8\u66F4",
  "hitl.outline.previewConfirm": "\u786E\u8BA4\u5957\u7528\u5927\u7EB2",
  "hitl.outline.previewApply": "\u9884\u89C8\u5E76\u5957\u7528\u5927\u7EB2",
  "hitl.outline.previewStats": "\u65B0\u589E {added} \u7B14 \xB7 \u5220\u9664 {removed} \u7B14 \xB7 \u5171 {total} \u7B14\u4E8B\u4EF6",
  "hitl.director.titlePlan": "\u7ED9 AI \u7684\u5BFC\u6F14\u7B14\u8BB0",
  "hitl.director.titleBStory": "\u544A\u8BC9 AI \u8FD9\u7AE0\u8981\u600E\u4E48\u53D1\u5C55\u8FD9\u6761\u526F\u7EBF\uFF1F",
  "hitl.director.placeholder": "\u7B80\u77ED\u8BF4\u660E\u672C\u7AE0\u65B9\u5411\u3001\u8282\u594F\u6216\u7981\u5FCC\u2026",
  "hitl.director.apply": "\u5957\u7528\u5E76\u7EE7\u7EED",
  "hitl.anchor.sectionTitle": "\u5EF6\u540E\u91CC\u7A0B\u7891\uFF08\u9009\u586B\uFF09",
  "hitl.anchor.hint": "\u82E5\u9700\u628A\u67D0\u4E2A\u6545\u4E8B\u8282\u70B9\u6539\u5230\u8F83\u665A\u7684\u7AE0\u518D\u8FBE\u6210\uFF0C\u8BF7\u586B\u5199\u540E\u9001\u51FA\uFF08\u4E0D\u5FC5\u5148\u70B9\u4E0A\u65B9\u300C\u5141\u8BB8\u5EF6\u540E\u300D\u4E5F\u53EF\u9001\u51FA\uFF09\u3002",
  "hitl.anchor.id": "\u91CC\u7A0B\u7891\u4EE3\u53F7",
  "hitl.anchor.chapter": "\u6539\u5230\u7B2C\u51E0\u7AE0",
  "hitl.anchor.submit": "\u5957\u7528\u5EF6\u671F\u5E76\u56DE\u5230\u5267\u60C5\u89C4\u5212",
  "hitl.draft.title": "\u4FEE\u6539\u7AE0\u8282\u6B63\u6587",
  "hitl.draft.hint": "\u4E13\u540D\u5BF9\u7167\u7EBF\u7D22\u8BF7\u5728\u4E0B\u6B21\u300C\u5F00\u59CB\u64B0\u5199\u672C\u7AE0\u300D\u65F6\u5728\u7AE0\u8282\u8BF7\u6C42\u4E00\u5E76\u9001\u51FA\u3002",
  "hitl.draft.mergeHints": "\u4FDD\u7559\u5DF2\u6536\u96C6\u7684\u4E13\u540D\u7EBF\u7D22",
  "hitl.draft.resumeLabel": "\u9700\u518D\u6B21\u68C0\u67E5\u5417\uFF1F",
  "hitl.draft.resume.reader": "\u4ECE\u9605\u8BFB\u68C0\u67E5\u518D\u8DD1",
  "hitl.draft.resume.draft_supervisor": "\u4ECE\u6B63\u6587\u5BA1\u6838\u518D\u8DD1",
  "hitl.draft.resume.author": "\u4ECE\u64B0\u5199\u518D\u8DD1",
  "hitl.draft.submit": "\u63D0\u4EA4\u6B63\u6587\u5E76\u7EE7\u7EED",
  "hitl.remap.title": "\u540D\u8BCD\u8FDE\u8FDE\u770B",
  "hitl.remap.hint": "\u5DE6\u4FA7\u4E3A\u8349\u7A3F\u4E2D\u7684\u4E0D\u660E\u8282\u70B9\uFF0C\u53F3\u4FA7\u8BF7\u9009\u62E9\u56FE\u8C31\u4E2D\u540C\u7C7B\u578B\u7684\u65E2\u6709\u8282\u70B9\u3002",
  "hitl.remap.leftPlaceholder": "\u9009\u62E9\u4E0D\u660E\u540D\u8BCD",
  "hitl.remap.rightPlaceholder": "\u9009\u62E9\u56FE\u8C31\u5BF9\u5E94",
  "hitl.remap.addRow": "\u65B0\u589E\u5BF9\u7167\u884C",
  "hitl.remap.previewTitle": "\u63D0\u4EA4\u524D\u9884\u89C8\uFF1A\u5BF9\u7167",
  "hitl.remap.previewConfirm": "\u786E\u8BA4\u5957\u7528\u5BF9\u7167",
  "hitl.remap.previewApply": "\u9884\u89C8\u5E76\u5957\u7528\u5BF9\u7167",
  "hitl.remap.noHints": "\u76EE\u524D\u6CA1\u6709\u7CFB\u7EDF\u731C\u6D4B\u8868\uFF0C\u8BF7\u6309\u5185\u6587\u81EA\u884C\u5BF9\u7167\u3002",
  "hitl.remap.waiveAdvanced": "\u53EF\u8DF3\u8FC7\u7684\u5FC5\u586B\u9879\uFF08\u9017\u53F7\uFF0C\u8FDB\u9636\uFF09",
  "hitl.remap.graphLoading": "\u6B63\u5728\u52A0\u8F7D\u56FE\u8C31\u2026",
  "hitl.remap.graphEmpty": "\u5C1A\u65E0\u56FE\u8C31\u6570\u636E\uFF0C\u8BF7\u7A0D\u5019\u6216\u5230\u56FE\u8C31\u9875\u5237\u65B0\u3002",
  "hitl.bStory.sectionTitle": "\u526F\u7EBF\u6536\u5C3E\u5224\u5B9A",
  "hitl.bStory.notesExpert": "\u8865\u5145\u8BF4\u660E\uFF08\u7ED3\u6848\u5206\u6790\uFF0C\u4F1A\u4E00\u5E76\u5B58\u6863\uFF09",
  "hitl.bStory.resolvedIds": "\u89C6\u4E3A\u5DF2\u6536\u5C3E\u7684\u526F\u7EBF\u4EE3\u53F7",
  "hitl.bStory.evidenceIds": "\u5F53\u4F5C\u8BC1\u636E\u7684\u60C5\u8282\u4E8B\u4EF6\u4EE3\u53F7",
  "hitl.bStory.rejectSubmit": "\u786E\u8BA4\u6253\u56DE\u5E76\u56DE\u5230\u6240\u9009\u6B65\u9AA4",
  "hitl.bStory.rejectCancel": "\u53D6\u6D88\uFF0C\u6539\u4E3A\u7ED3\u6848",
  "hitl.bStory.yes": "\u6CA1\u9519\uFF0C\u8FD9\u6761\u7EBF\u5DF2\u6B63\u5F0F\u5B8C\u7ED3",
  "hitl.bStory.no": "\u8FD8\u6CA1\u7ED3\u675F\uFF0C\u7EE7\u7EED\u53D1\u5C55",
  "hitl.bStory.noExpandLabel": "\u8FD8\u7F3A\u4E86\u4EC0\u4E48\u5267\u60C5\uFF1F\uFF08\u9009\u586B\uFF09",
  "hitl.bStory.rejectResume": "\u6253\u56DE\u540E\u4ECE\u54EA\u4E00\u6B65\u91CD\u6765",
  "hitl.bStory.resumeOption.extraction_gate": "\u8BBE\u5B9A\u5F52\u6863",
  "hitl.bStory.resumeOption.author": "\u64B0\u5199\u6B63\u6587",
  "hitl.bStory.resumeOption.b_story_resolve": "\u526F\u7EBF\u6536\u5C3E",
  "hitl.prune.title": "\u6E05\u7406\u53C2\u8003\u8BB0\u5FC6",
  "hitl.prune.hint": "\u9009\u62E9\u7CBE\u7B80\u7A0B\u5EA6\uFF1A\u6570\u5B57\u6108\u5927\uFF0C\u6108\u591A\u65E7\u7EC6\u8282\u4F1A\u88AB\u7F29\u51CF\u3002",
  "hitl.prune.tier0": "0\uFF1A\u5C3D\u91CF\u4FDD\u7559\u7EC6\u8282",
  "hitl.prune.tier1": "1\uFF1A\u4E2D\u5EA6\u5220\u51CF\u65E7\u5267\u60C5",
  "hitl.prune.tier2": "2\uFF1A\u79EF\u6781\u5931\u5FC6\uFF08\u4EC5\u4FDD\u7559\u5927\u4E3B\u7EBF\uFF09",
  "hitl.prune.apply": "\u5957\u7528\u5E76\u91CD\u65B0\u6574\u7406\u80CC\u666F",
  "hitl.preview.forceApproveTitle": "\u63D0\u4EA4\u524D\u9884\u89C8\uFF1A\u5F3A\u5236\u901A\u8FC7\u5927\u7EB2",
  "hitl.preview.forceApproveBullet1": "\u5C06\u76F4\u63A5\u4EE5\u5F53\u524D\u5927\u7EB2\u8FDB\u5165\u64B0\u5199\u3002",
  "hitl.preview.forceApproveBullet2": "\u540E\u7EED\u82E5\u903B\u8F91\u4E0D\u8DB3\uFF0C\u53EF\u80FD\u589E\u52A0\u8349\u7A3F\u91CD\u5199\u6210\u672C\u3002",
  "hitl.preview.forceApproveConfirm": "\u786E\u8BA4\u5F3A\u5236\u901A\u8FC7"
};

// src/i18n/I18nProvider.tsx
import { jsx } from "react/jsx-runtime";
var I18nContext = createContext(null);

// src/i18n/useI18n.ts
function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}

// src/i18n/runtimeLocale.ts
function getRuntimeLocale() {
  if (typeof window === "undefined") return "zh-Hant";
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (isLocale(stored)) return stored;
  return detectLocaleFromNavigator();
}

// src/features/hitl-panel/hitlCopy.ts
function pick(zhHant2, zhHans2, en) {
  const locale = getRuntimeLocale();
  if (locale === "en") return en;
  if (locale === "zh-Hans") return zhHans2;
  return zhHant2;
}
var HITL_REASON = {
  PLAN_LOOP: "Plan_Loop_Exceeded",
  DRAFT_LOOP: "Draft_Loop_Exceeded",
  EXTRACTION_GATE: "Extraction_Gate_Failed",
  B_STORY: "B_Story_Resolution_Failed",
  B_STORY_COOLDOWN: "B_Story_Cooldown_Violation",
  RESOLUTION_TACTIC: "Resolution_Tactic_Cooldown_Violation",
  ENDING_VIBE: "Ending_Vibe_Cooldown_Violation",
  CONTEXT: "Context_Length_Exceeded",
  ALIGNMENT_RULES_REQUIRED: "Alignment_Rules_Required",
  OUTPUT_LANGUAGE: "Output_Language_Mismatch"
};
var FLOW_STEPS = [
  { id: "director", userLabel: pick("\u7AE0\u7BC0\u65B9\u5411", "\u7AE0\u8282\u65B9\u5411", "Chapter Direction") },
  { id: "graph_rag", userLabel: pick("\u80CC\u666F\u6574\u7406", "\u80CC\u666F\u6574\u7406", "Context Prep") },
  { id: "planner", userLabel: pick("\u5287\u60C5\u898F\u5283", "\u5267\u60C5\u89C4\u5212", "Story Planning") },
  { id: "plan_supervisor", userLabel: pick("\u5927\u7DB1\u5BE9\u6838", "\u5927\u7EB2\u5BA1\u6838", "Outline Review") },
  { id: "logic_alignment", userLabel: pick("\u898F\u5247\u5C0D\u9F4A", "\u89C4\u5219\u5BF9\u9F50", "Logic Alignment") },
  { id: "author", userLabel: pick("\u64B0\u5BEB\u5167\u6587", "\u64B0\u5199\u6B63\u6587", "Write Draft") },
  { id: "draft_supervisor", userLabel: pick("\u5167\u6587\u5BE9\u6838", "\u6B63\u6587\u5BA1\u6838", "Draft Review") },
  { id: "reader", userLabel: pick("\u95B1\u8B80\u6AA2\u67E5", "\u9605\u8BFB\u68C0\u67E5", "Reader Check") },
  { id: "extraction_gate", userLabel: pick("\u8A2D\u5B9A\u6B78\u6A94", "\u8BBE\u5B9A\u5F52\u6863", "Extraction Gate") },
  { id: "b_story_resolve", userLabel: pick("\u526F\u7DDA\u6536\u5C3E", "\u526F\u7EBF\u6536\u5C3E", "Subplot Resolve") },
  { id: "state_updater", userLabel: pick("\u5B8C\u7A3F\u66F4\u65B0", "\u5B8C\u7A3F\u66F4\u65B0", "State Update") }
];
var RESUME_TO_STEP_INDEX = {
  director: 0,
  graph_rag: 1,
  planner: 2,
  plan_supervisor: 3,
  logic_alignment: 4,
  author: 5,
  draft_supervisor: 6,
  reader: 7,
  extraction_gate: 8,
  output_language_gate: 9,
  chapter_summarizer: 9,
  b_story_resolve: 9,
  state_updater: 10
};
var REASON_TO_STEP_INDEX = {
  [HITL_REASON.PLAN_LOOP]: 3,
  [HITL_REASON.RESOLUTION_TACTIC]: 3,
  [HITL_REASON.ENDING_VIBE]: 3,
  [HITL_REASON.B_STORY_COOLDOWN]: 0,
  [HITL_REASON.CONTEXT]: 1,
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: 4,
  [HITL_REASON.DRAFT_LOOP]: 5,
  [HITL_REASON.EXTRACTION_GATE]: 7,
  [HITL_REASON.B_STORY]: 8,
  [HITL_REASON.OUTPUT_LANGUAGE]: 9
};
function resumeNodeUserLabel(resumeFrom) {
  const idx = RESUME_TO_STEP_INDEX[resumeFrom.trim()];
  if (typeof idx === "number" && FLOW_STEPS[idx]) return FLOW_STEPS[idx].userLabel;
  return resumeFrom.trim() || "\u2014";
}
var HITL_SITUATION_COPY = {
  [HITL_REASON.PLAN_LOOP]: {
    title: pick("\u5927\u7DB1\u53CD\u8986\u672A\u904E\u5BE9", "\u5927\u7EB2\u53CD\u590D\u672A\u8FC7\u5BA1", "Outline Repeatedly Rejected"),
    why: pick(
      "\u9019\u4E00\u7AE0\u7684\u5287\u60C5\u898F\u5283\u591A\u6B21\u8ABF\u6574\u5F8C\uFF0C\u4ECD\u4E0D\u7B26\u5408\u7CFB\u7D71\u7684\u898F\u5247\u6216\u60A8\u7684\u6545\u4E8B\u8A2D\u5B9A\u3002\u9700\u8981\u60A8\u9078\u64C7\u4E0B\u4E00\u6B65\uFF1A\u653E\u5BEC\u67D0\u500B\u689D\u4EF6\u3001\u624B\u52D5\u6539\u5927\u7DB1\uFF0C\u6216\u8ABF\u6574\u7AE0\u7BC0\u65B9\u5411\u3002",
      "\u8FD9\u4E00\u7AE0\u7684\u5267\u60C5\u89C4\u5212\u591A\u6B21\u8C03\u6574\u540E\uFF0C\u4ECD\u4E0D\u7B26\u5408\u7CFB\u7EDF\u89C4\u5219\u6216\u4F60\u7684\u6545\u4E8B\u8BBE\u5B9A\u3002\u8BF7\u51B3\u5B9A\u4E0B\u4E00\u6B65\uFF1A\u653E\u5BBD\u6761\u4EF6\u3001\u624B\u52A8\u6539\u5927\u7EB2\uFF0C\u6216\u8C03\u6574\u7AE0\u8282\u65B9\u5411\u3002",
      "This chapter plan still fails system rules or your story settings after multiple revisions. Choose a next step: relax constraints, edit outline manually, or tune chapter direction."
    )
  },
  [HITL_REASON.DRAFT_LOOP]: {
    title: pick("\u5167\u6587\u5BE9\u6838\u591A\u6B21\u672A\u904E", "\u6B63\u6587\u5BA1\u6838\u591A\u6B21\u672A\u8FC7", "Draft Rejected Multiple Times"),
    why: pick(
      "\u7AE0\u7BC0\u5167\u6587\u5DF2\u91CD\u5BEB\u591A\u6B21\uFF0C\u4ECD\u8207\u76EE\u6A19\uFF08\u9577\u5EA6\u3001\u7BC0\u594F\u6216\u4E00\u81F4\u6027\uFF09\u6709\u843D\u5DEE\u3002\u60A8\u53EF\u4EE5\u653E\u5BEC\u5B57\u6578\u3001\u76F4\u63A5\u4FEE\u6539\u5167\u6587\uFF0C\u6216\u88DC\u4E0A\u6587\u4E2D\u61C9\u51FA\u73FE\u7684\u7A31\u547C\u8207\u5C08\u540D\u7DDA\u7D22\u3002",
      "\u7AE0\u8282\u6B63\u6587\u5DF2\u91CD\u5199\u591A\u6B21\uFF0C\u4ECD\u4E0E\u76EE\u6807\uFF08\u957F\u5EA6\u3001\u8282\u594F\u6216\u4E00\u81F4\u6027\uFF09\u6709\u843D\u5DEE\u3002\u4F60\u53EF\u4EE5\u653E\u5BBD\u5B57\u6570\u3001\u76F4\u63A5\u4FEE\u6539\u6B63\u6587\uFF0C\u6216\u8865\u4E0A\u5E94\u51FA\u73B0\u7684\u79F0\u547C\u4E0E\u4E13\u540D\u7EBF\u7D22\u3002",
      "The chapter draft has been rewritten multiple times but still misses targets (length, pacing, or consistency). You can relax word count, edit draft directly, or add naming hints."
    )
  },
  [HITL_REASON.EXTRACTION_GATE]: {
    title: pick("\u8A2D\u5B9A\u8207\u5167\u6587\u5C0D\u4E0D\u8D77\u4F86", "\u8BBE\u5B9A\u4E0E\u6B63\u6587\u5BF9\u4E0D\u4E0A", "Canon and Draft Mismatch"),
    why: pick(
      "\u7CFB\u7D71\u8981\u628A\u672C\u7AE0\u51FA\u73FE\u7684\u4EBA\u3001\u4E8B\u3001\u7269\u8A18\u9032\u6545\u4E8B\u8A2D\u5B9A\u6642\uFF0C\u767C\u73FE\u540D\u7A31\u6216\u5C0D\u61C9\u95DC\u4FC2\u5C0D\u4E0D\u4E0A\u3002\u8ACB\u5354\u52A9\u5C0D\u7167\u3001\u4FEE\u6B63\u6620\u5C04\uFF0C\u6216\u5148\u56DE\u53BB\u6539\u5167\u6587\u518D\u8A66\u4E00\u6B21\u3002",
      "\u7CFB\u7EDF\u5728\u628A\u672C\u7AE0\u4EBA\u7269/\u4E8B\u4EF6/\u7269\u4EF6\u5199\u56DE\u8BBE\u5B9A\u65F6\uFF0C\u53D1\u73B0\u540D\u79F0\u6216\u6620\u5C04\u5173\u7CFB\u4E0D\u4E00\u81F4\u3002\u8BF7\u534F\u52A9\u5BF9\u7167\u4FEE\u6B63\uFF0C\u6216\u5148\u56DE\u53BB\u4FEE\u6539\u6B63\u6587\u518D\u8BD5\u3002",
      "When archiving people/events/items from this chapter into canon, the system found naming or mapping mismatches. Please fix mappings, or revise draft first and retry."
    )
  },
  [HITL_REASON.B_STORY]: {
    title: pick("\u526F\u7DDA\u6536\u5C3E\u9700\u8981\u60A8\u62CD\u677F", "\u526F\u7EBF\u6536\u5C3E\u9700\u8981\u4F60\u62CD\u677F", "Subplot Resolution Needs Decision"),
    why: pick(
      "\u7CFB\u7D71\u7121\u6CD5\u81EA\u52D5\u5224\u5B9A\u67D0\u689D\u526F\u7DDA\u662F\u5426\u5DF2\u5408\u7406\u6536\u675F\u3002\u8ACB\u4F9D\u60A8\u7684\u5275\u4F5C\u610F\u5716\uFF0C\u6C7A\u5B9A\u662F\u5426\u8996\u70BA\u5DF2\u6536\u5C3E\uFF0C\u6216\u8981\u6C42\u56DE\u5230\u524D\u6BB5\u6D41\u7A0B\u4FEE\u6539\u3002",
      "\u7CFB\u7EDF\u65E0\u6CD5\u81EA\u52A8\u5224\u5B9A\u67D0\u6761\u526F\u7EBF\u662F\u5426\u5DF2\u5408\u7406\u6536\u675F\u3002\u8BF7\u6309\u4F60\u7684\u521B\u4F5C\u610F\u56FE\u51B3\u5B9A\u662F\u5426\u89C6\u4E3A\u5DF2\u6536\u5C3E\uFF0C\u6216\u6253\u56DE\u524D\u6BB5\u6D41\u7A0B\u4FEE\u6539\u3002",
      "The system cannot confidently decide whether a subplot is properly resolved. Decide whether to mark it resolved or send the flow back for revision."
    )
  },
  [HITL_REASON.B_STORY_COOLDOWN]: {
    title: pick("\u526F\u7DDA\u985E\u578B\u649E\u671F", "\u526F\u7EBF\u7C7B\u578B\u649E\u671F", "Subplot Type Cooldown Conflict"),
    why: pick(
      "\u672C\u7AE0\u60F3\u8D70\u7684\u526F\u7DDA\u985E\u578B\uFF0C\u8207\u8FD1\u671F\u7AE0\u7BC0\u7528\u904E\u7684\u592A\u63A5\u8FD1\u3002\u8ACB\u5FAE\u8ABF\u7AE0\u7BC0\u65B9\u5411\u6216\u526F\u7DDA\u6307\u793A\uFF0C\u8B93\u6545\u4E8B\u7BC0\u594F\u66F4\u6709\u8B8A\u5316\u3002",
      "\u672C\u7AE0\u60F3\u8D70\u7684\u526F\u7EBF\u7C7B\u578B\uFF0C\u4E0E\u8FD1\u671F\u7AE0\u8282\u7528\u8FC7\u7684\u592A\u63A5\u8FD1\u3002\u8BF7\u5FAE\u8C03\u7AE0\u8282\u65B9\u5411\u6216\u526F\u7EBF\u6307\u793A\uFF0C\u8BA9\u8282\u594F\u66F4\u6709\u53D8\u5316\u3002",
      "The subplot type planned for this chapter is too similar to recent chapters. Tune chapter direction or subplot directive to add variation."
    )
  },
  [HITL_REASON.RESOLUTION_TACTIC]: {
    title: pick("\u6536\u5C3E\u65B9\u5F0F\u8207\u8FD1\u671F\u91CD\u8907", "\u6536\u5C3E\u65B9\u5F0F\u4E0E\u8FD1\u671F\u91CD\u590D", "Ending Tactic Repeats Recent Chapters"),
    why: pick(
      "\u5927\u7DB1\u88E1\u7684\u6536\u5C3E\u65B9\u5F0F\uFF08\u4F8B\u5982\u7279\u5B9A\u6232\u5287\u624B\u6BB5\uFF09\u8207\u7CFB\u7D71\u7684\u300C\u51B7\u537B\u300D\u898F\u5247\u885D\u7A81\u3002\u8ACB\u8ABF\u6574\u5927\u7DB1\u6558\u4E8B\u6216\u7AE0\u7BC0\u65B9\u5411\u5F8C\u518D\u7E7C\u7E8C\u3002",
      "\u5927\u7EB2\u91CC\u7684\u6536\u5C3E\u65B9\u5F0F\uFF08\u4F8B\u5982\u7279\u5B9A\u620F\u5267\u624B\u6BB5\uFF09\u4E0E\u7CFB\u7EDF\u201C\u51B7\u5374\u201D\u89C4\u5219\u51B2\u7A81\u3002\u8BF7\u8C03\u6574\u5927\u7EB2\u53D9\u4E8B\u6216\u7AE0\u8282\u65B9\u5411\u540E\u7EE7\u7EED\u3002",
      "The ending tactic in your outline conflicts with cooldown rules. Adjust narrative approach or chapter direction before continuing."
    )
  },
  [HITL_REASON.ENDING_VIBE]: {
    title: pick("\u7D50\u5C3E\u6C1B\u570D\u8207\u8FD1\u671F\u91CD\u8907", "\u7ED3\u5C3E\u6C1B\u56F4\u4E0E\u8FD1\u671F\u91CD\u590D", "Ending Vibe Repeats Recent Chapters"),
    why: pick(
      "\u672C\u7AE0\u7D50\u5C3E\u7684\u6C1B\u570D\u6216\u5834\u666F\u985E\u578B\uFF0C\u8207\u8FD1\u671F\u7AE0\u7BC0\u592A\u50CF\u3002\u8ACB\u8ABF\u6574\u5927\u7DB1\u6216\u6558\u4E8B\u8D70\u5411\uFF0C\u907F\u514D\u8B80\u8005\u611F\u5230\u91CD\u8907\u3002",
      "\u672C\u7AE0\u7ED3\u5C3E\u6C1B\u56F4\u6216\u573A\u666F\u7C7B\u578B\u4E0E\u8FD1\u671F\u7AE0\u8282\u592A\u50CF\u3002\u8BF7\u8C03\u6574\u5927\u7EB2\u6216\u53D9\u4E8B\u8D70\u5411\uFF0C\u907F\u514D\u8BFB\u8005\u611F\u89C9\u91CD\u590D\u3002",
      "The ending vibe or scene type is too similar to recent chapters. Adjust outline or narrative direction to avoid repetition."
    )
  },
  [HITL_REASON.CONTEXT]: {
    title: pick("\u53C3\u8003\u8CC7\u6599\u91CF\u904E\u5927", "\u53C2\u8003\u8D44\u6599\u91CF\u8FC7\u5927", "Context Too Large"),
    why: pick(
      "\u7CFB\u7D71\u6E96\u5099\u5BEB\u4F5C\u80CC\u666F\u6642\uFF0C\u4E00\u6B21\u8F09\u5165\u7684\u5167\u5BB9\u8D85\u904E\u4E0A\u9650\u3002\u8ACB\u522A\u6E1B\u6216\u7CBE\u7C21\u5404\u6BB5\u53C3\u8003\u6587\u5B57\u5F8C\u518D\u7E7C\u7E8C\u3002",
      "\u7CFB\u7EDF\u51C6\u5907\u5199\u4F5C\u80CC\u666F\u65F6\uFF0C\u5355\u6B21\u8F7D\u5165\u5185\u5BB9\u8D85\u8FC7\u4E0A\u9650\u3002\u8BF7\u5220\u51CF\u6216\u7CBE\u7B80\u5404\u6BB5\u53C2\u8003\u6587\u5B57\u540E\u7EE7\u7EED\u3002",
      "Loaded context exceeded limits during background assembly. Trim reference sections and continue."
    )
  },
  [HITL_REASON.ALIGNMENT_RULES_REQUIRED]: {
    title: pick("\u5075\u6E2C\u5230\u8907\u96DC\u667A\u9B25\uFF0C\u9700\u88DC\u5145\u898F\u5247", "\u68C0\u6D4B\u5230\u590D\u6742\u667A\u6597\uFF0C\u9700\u8865\u5145\u89C4\u5219", "Complex Mind-Game Detected"),
    why: pick(
      "\u8349\u7A3F\u5305\u542B\u9AD8\u8907\u96DC\u667A\u9B25\u5143\u7D20\uFF0C\u4F46\u7F3A\u5C11\u53EF\u57F7\u884C\u7684\u786C\u6027\u898F\u5247\u3002\u8ACB\u88DC\u5145\u52DD\u8CA0\u689D\u4EF6\u3001\u56DE\u5408/\u5224\u5B9A\u6D41\u7A0B\u8207\u7C4C\u78BC\u4EE3\u50F9\uFF0C\u7CFB\u7D71\u624D\u80FD\u5B89\u5168\u5C0D\u9F4A\u5F8C\u7E8C\u6B63\u6587\u3002",
      "\u8349\u7A3F\u5305\u542B\u9AD8\u590D\u6742\u667A\u6597\u5143\u7D20\uFF0C\u4F46\u7F3A\u5C11\u53EF\u6267\u884C\u786C\u6027\u89C4\u5219\u3002\u8BF7\u8865\u5145\u80DC\u8D1F\u6761\u4EF6\u3001\u56DE\u5408/\u5224\u5B9A\u6D41\u7A0B\u4E0E\u7B79\u7801\u4EE3\u4EF7\uFF0C\u7CFB\u7EDF\u624D\u80FD\u5B89\u5168\u5BF9\u9F50\u540E\u7EED\u6B63\u6587\u3002",
      "Draft contains complex strategy conflicts but lacks executable hard rules. Add win conditions, round/judging flow, and stakes so later drafting can align safely."
    )
  },
  [HITL_REASON.OUTPUT_LANGUAGE]: {
    title: pick("\u8F38\u51FA\u8A9E\u8A00\u8207\u5C08\u6848\u8A2D\u5B9A\u4E0D\u4E00\u81F4", "\u8F93\u51FA\u8BED\u8A00\u4E0E\u9879\u76EE\u8BBE\u5B9A\u4E0D\u4E00\u81F4", "Output Language Mismatch"),
    why: pick(
      "\u7CFB\u7D71\u7528\u7C21\u55AE\u898F\u5247\u6AA2\u67E5\u672C\u7AE0\u6B63\u6587\u7684\u4E3B\u8981\u5B57\u6BCD\u985E\u578B\uFF0C\u767C\u73FE\u53EF\u80FD\u8207\u6545\u4E8B\u300C\u8F38\u51FA\u8A9E\u8A00\u300D\u8A2D\u5B9A\u4E0D\u7B26\u3002\u60A8\u53EF\u4EE5\u9000\u56DE\u64B0\u5BEB\u4F9D\u8A2D\u5B9A\u8A9E\u8A00\u91CD\u5BEB\uFF0C\u6216\u78BA\u8A8D\u5F8C\u7565\u904E\u6AA2\u67E5\u7E7C\u7E8C\u5F59\u7E3D\u3002",
      "\u7CFB\u7EDF\u7528\u7B80\u5355\u89C4\u5219\u68C0\u67E5\u672C\u7AE0\u6B63\u6587\u7684\u4E3B\u8981\u5B57\u7B26\u7C7B\u578B\uFF0C\u53D1\u73B0\u53EF\u80FD\u4E0E\u6545\u4E8B\u201C\u8F93\u51FA\u8BED\u8A00\u201D\u8BBE\u5B9A\u4E0D\u7B26\u3002\u4F60\u53EF\u4EE5\u56DE\u5230\u64B0\u5199\u6309\u8BBE\u5B9A\u91CD\u5199\uFF0C\u6216\u786E\u8BA4\u540E\u7565\u8FC7\u68C0\u67E5\u7EE7\u7EED\u6C47\u603B\u3002",
      "Simple language detection suggests this chapter may not match the project's output language setting. You can return to rewrite in target language, or confirm and continue."
    )
  }
};
function getSituationCopy(reason) {
  return HITL_SITUATION_COPY[reason] ?? {
    title: pick("\u6D41\u7A0B\u9700\u8981\u60A8\u5354\u52A9", "\u6D41\u7A0B\u9700\u8981\u4F60\u534F\u52A9", "Your input is required"),
    why: pick("\u7CFB\u7D71\u5728\u6B64\u6B65\u9A5F\u66AB\u505C\uFF0C\u8ACB\u4F9D\u4E0B\u65B9\u9078\u9805\u6216\u8868\u55AE\u8655\u7406\u5F8C\u518D\u7E7C\u7E8C\u3002", "\u7CFB\u7EDF\u5728\u6B64\u6B65\u9AA4\u6682\u505C\uFF0C\u8BF7\u6839\u636E\u4E0B\u65B9\u9009\u9879\u6216\u8868\u5355\u5904\u7406\u540E\u7EE7\u7EED\u3002", "The workflow is paused at this step. Use the options or form below to continue.")
  };
}
var OPTION_DECISION_HINTS = {
  allow_adjust_anchor: pick(
    "\u5148\u9078\u9019\u500B\u5F8C\uFF0C\u518D\u5230\u4E0B\u65B9\u7528\u300C\u5EF6\u5F8C\u91CC\u7A0B\u7891\u300D\u6307\u5B9A\u8981\u5EF6\u5230\u54EA\u4E00\u7AE0\u3002",
    "\u5148\u9009\u8FD9\u4E2A\uFF0C\u518D\u5230\u4E0B\u65B9\u7528\u201C\u5EF6\u540E\u91CC\u7A0B\u7891\u201D\u6307\u5B9A\u8981\u5EF6\u5230\u54EA\u4E00\u7AE0\u3002",
    "Choose this first, then set the target chapter in Delay Milestone below."
  ),
  force_rewrite_plan: pick(
    "\u6E05\u7A7A\u5927\u7DB1\u91CD\u8A66\u8A08\u6B21\uFF0C\u4E26\u4EE5\u60A8\u624B\u52D5\u7DE8\u8F2F\u5F8C\u7684\u5927\u7DB1\u91CD\u65B0\u898F\u5283\u3002",
    "\u6E05\u7A7A\u5927\u7EB2\u91CD\u8BD5\u8BA1\u6B21\uFF0C\u5E76\u4EE5\u4F60\u624B\u52A8\u7F16\u8F91\u540E\u7684\u5927\u7EB2\u91CD\u65B0\u89C4\u5212\u3002",
    "Reset outline retry count and re-plan from your edited outline."
  ),
  force_approve_plan: pick(
    "\u63A5\u53D7\u76EE\u524D\u5927\u7DB1\uFF0C\u76F4\u63A5\u9032\u5165\u64B0\u5BEB\uFF08\u8ACB\u78BA\u8A8D\u60A8\u9858\u610F\u627F\u64D4\u5F8C\u7E8C\u98A8\u96AA\uFF09\u3002",
    "\u63A5\u53D7\u5F53\u524D\u5927\u7EB2\uFF0C\u76F4\u63A5\u8FDB\u5165\u64B0\u5199\uFF08\u8BF7\u786E\u8BA4\u4F60\u613F\u610F\u627F\u62C5\u540E\u7EED\u98CE\u9669\uFF09\u3002",
    "Accept current outline and move to writing (with downstream risk)."
  ),
  keep_current_logic: pick(
    "\u7DAD\u6301\u5287\u60C5\u908F\u8F2F\uFF0C\u91CD\u7F6E\u5167\u6587\u91CD\u8A66\u6B21\u6578\uFF0C\u8ACB\u63A5\u8457\u4FEE\u6539\u6B63\u6587\u6216\u88DC\u7DDA\u7D22\u3002",
    "\u7EF4\u6301\u5267\u60C5\u903B\u8F91\uFF0C\u91CD\u7F6E\u6B63\u6587\u91CD\u8BD5\u6B21\u6570\uFF0C\u8BF7\u7EE7\u7EED\u4FEE\u6539\u6B63\u6587\u6216\u8865\u7EBF\u7D22\u3002",
    "Keep current logic, reset draft retries, then revise draft or add hints."
  ),
  relax_word_count: pick(
    "\u653E\u5BEC\u5B57\u6578\u76EE\u6A19\u7D04\u56DB\u6210\uFF0C\u8B93\u5167\u6587\u5BE9\u6838\u8F03\u6613\u901A\u904E\u3002",
    "\u653E\u5BBD\u5B57\u6570\u76EE\u6807\u7EA6\u56DB\u6210\uFF0C\u8BA9\u6B63\u6587\u5BA1\u6838\u66F4\u5BB9\u6613\u901A\u8FC7\u3002",
    "Relax word-count target by around 40% for easier draft validation."
  ),
  extraction_return_author: pick(
    "\u5148\u4E0D\u5C0D\u7167\u8A2D\u5B9A\u8868\uFF0C\u56DE\u5230\u64B0\u5BEB\u968E\u6BB5\u4FEE\u6539\u5167\u6587\u7528\u8A5E\u8207\u6307\u6D89\u3002",
    "\u5148\u4E0D\u5BF9\u7167\u8BBE\u5B9A\u8868\uFF0C\u56DE\u5230\u64B0\u5199\u9636\u6BB5\u4FEE\u6539\u6B63\u6587\u7528\u8BCD\u4E0E\u6307\u6D89\u3002",
    "Skip mapping for now and return to writing to revise wording/references."
  ),
  language_return_author: pick(
    "\u56DE\u5230\u64B0\u5BEB\uFF0C\u4F9D\u5C08\u6848\u8A2D\u5B9A\u7684\u8F38\u51FA\u8A9E\u8A00\u91CD\u5BEB\u672C\u7AE0\u6B63\u6587\u3002",
    "\u56DE\u5230\u64B0\u5199\uFF0C\u6309\u9879\u76EE\u8BBE\u5B9A\u7684\u8F93\u51FA\u8BED\u8A00\u91CD\u5199\u672C\u7AE0\u6B63\u6587\u3002",
    "Return to writing and rewrite this chapter in project output language."
  ),
  language_force_continue: pick(
    "\u63A5\u53D7\u76EE\u524D\u6B63\u6587\u4E26\u7565\u904E\u8A9E\u8A00\u6AA2\u67E5\uFF0C\u7E7C\u7E8C\u9032\u5165\u7AE0\u7BC0\u5F59\u7E3D\u8207\u6536\u5C3E\u6D41\u7A0B\u3002",
    "\u63A5\u53D7\u5F53\u524D\u6B63\u6587\u5E76\u7565\u8FC7\u8BED\u8A00\u68C0\u67E5\uFF0C\u7EE7\u7EED\u8FDB\u5165\u7AE0\u8282\u6C47\u603B\u4E0E\u6536\u5C3E\u6D41\u7A0B\u3002",
    "Accept current draft, skip language check, and continue to wrap-up."
  )
};
function asRecord(v) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : null;
}
var PLAN_VIOLATION_HINTS = {
  ANCHOR: pick("\u8207\u6545\u4E8B\u91CC\u7A0B\u7891\u4E0D\u4E00\u81F4", "\u4E0E\u6545\u4E8B\u91CC\u7A0B\u7891\u4E0D\u4E00\u81F4", "Conflicts with story milestone"),
  LENGTH: pick("\u9577\u5EA6\u76EE\u6A19\u4E0D\u7B26", "\u957F\u5EA6\u76EE\u6807\u4E0D\u7B26", "Length target mismatch"),
  COOLDOWN: pick("\u8207\u8FD1\u671F\u7AE0\u7BC0\u7BC0\u594F\u898F\u5247\u885D\u7A81", "\u4E0E\u8FD1\u671F\u7AE0\u8282\u8282\u594F\u89C4\u5219\u51B2\u7A81", "Conflicts with recent chapter cooldown rules"),
  B_STORY: pick("\u526F\u7DDA\u76F8\u95DC", "\u526F\u7EBF\u76F8\u5173", "Subplot-related"),
  RESOLUTION_COOLDOWN_HARD_VIOLATION: pick(
    "\u6536\u5C3E\u65B9\u5F0F\u8207\u51B7\u537B\u898F\u5247\u885D\u7A81",
    "\u6536\u5C3E\u65B9\u5F0F\u4E0E\u51B7\u5374\u89C4\u5219\u51B2\u7A81",
    "Ending tactic conflicts with cooldown rules"
  ),
  ENDING_VIBE_COOLDOWN_HARD_VIOLATION: pick(
    "\u7D50\u5C3E\u6C1B\u570D\u8207\u51B7\u537B\u898F\u5247\u885D\u7A81",
    "\u7ED3\u5C3E\u6C1B\u56F4\u4E0E\u51B7\u5374\u89C4\u5219\u51B2\u7A81",
    "Ending vibe conflicts with cooldown rules"
  )
};
function planViolationFriendly(code) {
  const c = code.trim();
  if (!c) return "";
  const hint = PLAN_VIOLATION_HINTS[c];
  if (hint) return `${hint}\uFF08${c}\uFF09`;
  if (/^[A-Z0-9_]+$/.test(c)) {
    return pick(`\u7CFB\u7D71\u4EE3\u78BC\uFF1A${c}`, `\u7CFB\u7EDF\u4EE3\u7801\uFF1A${c}`, `System code: ${c}`);
  }
  return c;
}
function buildFeedbackSummary(state, reason) {
  const lines = [];
  if (reason === HITL_REASON.PLAN_LOOP || reason === HITL_REASON.RESOLUTION_TACTIC || reason === HITL_REASON.ENDING_VIBE) {
    const pf = state.plan_feedback;
    if (Array.isArray(pf) && pf.length > 0) {
      const last = pf[pf.length - 1];
      const row = asRecord(last);
      if (row) {
        const msg = String(row.message ?? "").trim();
        const viol = String(row.violation ?? "").trim();
        if (msg) lines.push(pick(`\u5BE9\u6838\u610F\u898B\uFF1A${msg}`, `\u5BA1\u6838\u610F\u89C1\uFF1A${msg}`, `Review note: ${msg}`));
        else if (viol) {
          lines.push(
            pick(
              `\u554F\u984C\u985E\u578B\uFF1A${planViolationFriendly(viol)}`,
              `\u95EE\u9898\u7C7B\u578B\uFF1A${planViolationFriendly(viol)}`,
              `Issue type: ${planViolationFriendly(viol)}`
            )
          );
        }
      }
    }
    const pw = state.plan_warnings;
    if (Array.isArray(pw) && pw.length > 0) {
      const tail = pw.slice(-3).map((w) => String(w).trim()).filter(Boolean);
      if (tail.length) {
        lines.push(
          pick(`\u63D0\u9192\uFF1A${tail.join("\uFF1B")}`, `\u63D0\u9192\uFF1A${tail.join("\uFF1B")}`, `Reminder: ${tail.join("; ")}`)
        );
      }
    }
  }
  if (reason === HITL_REASON.DRAFT_LOOP || reason === HITL_REASON.EXTRACTION_GATE) {
    const df = state.draft_feedback;
    if (Array.isArray(df) && df.length > 0) {
      const last = df[df.length - 1];
      const row = asRecord(last);
      if (row) {
        const msg = String(row.message ?? "").trim();
        if (msg) lines.push(pick(`\u5BE9\u7A3F\u56DE\u994B\uFF1A${msg}`, `\u5BA1\u7A3F\u53CD\u9988\uFF1A${msg}`, `Draft feedback: ${msg}`));
      }
    }
  }
  if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
    const al = String(state.alignment_log ?? "").trim();
    if (al) {
      const clipped = al.length > 420 ? `${al.slice(0, 420)}\u2026` : al;
      lines.push(pick(`\u5C0D\u9F4A\u65E5\u8A8C\uFF1A${clipped}`, `\u5BF9\u9F50\u65E5\u5FD7\uFF1A${clipped}`, `Alignment log: ${clipped}`));
    }
    const cn = state.human_outline_conflict_notes;
    if (Array.isArray(cn)) {
      for (const x of cn.slice(0, 5)) {
        const s = String(x).trim();
        if (s) lines.push(pick(`\u8A2D\u5B9A\u885D\u7A81\uFF1A${s}`, `\u8BBE\u5B9A\u51B2\u7A81\uFF1A${s}`, `Setting conflict: ${s}`));
      }
    }
    const co = String(state.chapter_outline ?? "").trim();
    if (co) {
      const clipped = co.length > 180 ? `${co.slice(0, 180)}\u2026` : co;
      lines.push(
        pick(
          `\u4F60\u7684\u4EBA\u985E\u5927\u7DB1\uFF08\u7BC0\u9304\uFF09\uFF1A${clipped}`,
          `\u4F60\u7684\u4EBA\u7C7B\u5927\u7EB2\uFF08\u8282\u5F55\uFF09\uFF1A${clipped}`,
          `Your outline (excerpt): ${clipped}`
        )
      );
    }
  }
  return lines.slice(0, 8);
}
function formatBStoryCandidateForDisplay(raw) {
  try {
    const v = JSON.parse(raw);
    const o = asRecord(v);
    if (!o) return { bullets: [], rawJson: raw };
    const bullets = [];
    for (const [k, val] of Object.entries(o)) {
      if (val == null || val === "") continue;
      const s = typeof val === "object" ? JSON.stringify(val) : String(val);
      if (s.length > 200) bullets.push(`${k}\uFF1A${s.slice(0, 200)}\u2026`);
      else bullets.push(`${k}\uFF1A${s}`);
    }
    return { bullets: bullets.slice(0, 12), rawJson: raw };
  } catch {
    return { bullets: [], rawJson: raw };
  }
}
var DRAFT_RESUME_OPTIONS = [
  { value: "reader", label: pick("\u5F9E\u95B1\u8B80\u6AA2\u67E5\u518D\u8DD1", "\u4ECE\u9605\u8BFB\u68C0\u67E5\u518D\u8DD1", "Resume from Reader Check") },
  { value: "draft_supervisor", label: pick("\u5F9E\u5167\u6587\u5BE9\u6838\u518D\u8DD1", "\u4ECE\u6B63\u6587\u5BA1\u6838\u518D\u8DD1", "Resume from Draft Review") },
  { value: "author", label: pick("\u5F9E\u64B0\u5BEB\u518D\u8DD1", "\u4ECE\u64B0\u5199\u518D\u8DD1", "Resume from Writing") }
];
var HINTS_RESUME_OPTIONS = [
  { value: "draft_supervisor", label: pick("\u5148\u7D66\u5167\u6587\u5BE9\u6838\u770B", "\u5148\u7ED9\u6B63\u6587\u5BA1\u6838\u770B", "Send to Draft Review first") },
  { value: "extraction_gate", label: pick("\u5FEB\u5230\u6B78\u6A94\u6642\u518D\u9A57\u8B49", "\u5230\u5F52\u6863\u524D\u518D\u9A8C\u8BC1", "Validate near extraction step") },
  { value: "author", label: pick("\u76F4\u63A5\u56DE\u5230\u64B0\u5BEB", "\u76F4\u63A5\u56DE\u5230\u64B0\u5199", "Return to Writing directly") }
];
var B_STORY_REJECT_RESUME_OPTIONS = [
  { value: "extraction_gate", label: pick("\u8A2D\u5B9A\u6B78\u6A94", "\u8BBE\u5B9A\u5F52\u6863", "Extraction Gate") },
  { value: "author", label: pick("\u64B0\u5BEB\u5167\u6587", "\u64B0\u5199\u6B63\u6587", "Write Draft") },
  { value: "b_story_resolve", label: pick("\u526F\u7DDA\u6536\u5C3E", "\u526F\u7EBF\u6536\u5C3E", "Subplot Resolve") }
];
function isPlanFamilyReason(reason) {
  return reason === HITL_REASON.PLAN_LOOP || reason === HITL_REASON.RESOLUTION_TACTIC || reason === HITL_REASON.ENDING_VIBE;
}
function isDirectorPatchReason(reason) {
  return isPlanFamilyReason(reason) || reason === HITL_REASON.B_STORY_COOLDOWN;
}
function solutionsForReason(reason) {
  if (reason === HITL_REASON.PLAN_LOOP) {
    return [
      {
        id: "outline",
        title: pick("\u624B\u52D5\u8ABF\u6574\u4E8B\u4EF6\u5927\u7DB1", "\u624B\u52A8\u8C03\u6574\u4E8B\u4EF6\u5927\u7EB2", "Manually Edit Event Outline"),
        blurb: pick(
          "\u76F4\u63A5\u7DE8\u8F2F\u4E8B\u4EF6\u8868\u8207\u8868\u5C64\u6558\u4E8B\uFF0C\u4EA4\u7D66\u7CFB\u7D71\u91CD\u65B0\u898F\u5283\u7D30\u7BC0\u3002",
          "\u76F4\u63A5\u7F16\u8F91\u4E8B\u4EF6\u8868\u4E0E\u8868\u5C42\u53D9\u4E8B\uFF0C\u4EA4\u7ED9\u7CFB\u7EDF\u91CD\u65B0\u89C4\u5212\u7EC6\u8282\u3002",
          "Directly edit events and narrative script, then let system re-plan details."
        )
      },
      {
        id: "director",
        title: pick("\u5FAE\u8ABF\u7AE0\u7BC0\u65B9\u5411", "\u5FAE\u8C03\u7AE0\u8282\u65B9\u5411", "Tune Chapter Direction"),
        blurb: pick(
          "\u8ABF\u6574\u672C\u7AE0\u985E\u578B\u3001\u4E3B\u7DDA\u6307\u793A\u3001\u60F3\u65B0\u767B\u5834\u7684\u5143\u7D20\u7B49\u3002",
          "\u8C03\u6574\u672C\u7AE0\u7C7B\u578B\u3001\u4E3B\u7EBF\u6307\u793A\u3001\u60F3\u65B0\u767B\u573A\u7684\u5143\u7D20\u7B49\u3002",
          "Adjust chapter type, narrative directive, and new elements."
        )
      }
    ];
  }
  if (isPlanFamilyReason(reason) && reason !== HITL_REASON.PLAN_LOOP) {
    return [
      {
        id: "outline",
        title: pick("\u8ABF\u6574\u5927\u7DB1\u8207\u6558\u4E8B", "\u8C03\u6574\u5927\u7EB2\u4E0E\u53D9\u4E8B", "Adjust Outline and Narrative"),
        blurb: pick(
          "\u4FEE\u6539\u4E8B\u4EF6\u8207\u6558\u4E8B\u8D70\u5411\uFF0C\u907F\u958B\u91CD\u8907\u7684\u6536\u5C3E\u6216\u6C1B\u570D\u3002",
          "\u4FEE\u6539\u4E8B\u4EF6\u4E0E\u53D9\u4E8B\u8D70\u5411\uFF0C\u907F\u5F00\u91CD\u590D\u7684\u6536\u5C3E\u6216\u6C1B\u56F4\u3002",
          "Adjust event flow to avoid repeated ending tactics or vibe."
        )
      },
      {
        id: "director",
        title: pick("\u5FAE\u8ABF\u7AE0\u7BC0\u65B9\u5411", "\u5FAE\u8C03\u7AE0\u8282\u65B9\u5411", "Tune Chapter Direction"),
        blurb: pick("\u5F9E\u7AE0\u7BC0\u5B9A\u4F4D\u8207\u526F\u7DDA\u6307\u793A\u4E0B\u624B\uFF0C\u8B93\u898F\u5283\u66F4\u5BB9\u6613\u904E\u5BE9\u3002", "\u4ECE\u7AE0\u8282\u5B9A\u4F4D\u4E0E\u526F\u7EBF\u6307\u793A\u4E0B\u624B\uFF0C\u8BA9\u89C4\u5212\u66F4\u5BB9\u6613\u8FC7\u5BA1\u3002", "Refine chapter positioning and subplot guidance to pass review.")
      }
    ];
  }
  if (reason === HITL_REASON.B_STORY_COOLDOWN) {
    return [
      {
        id: "director",
        title: pick("\u8ABF\u6574\u526F\u7DDA\u8207\u7AE0\u7BC0\u65B9\u5411", "\u8C03\u6574\u526F\u7EBF\u4E0E\u7AE0\u8282\u65B9\u5411", "Adjust Subplot and Direction"),
        blurb: pick("\u63DB\u4E00\u7A2E\u526F\u7DDA\u985E\u578B\u6216\u5BEB\u6CD5\uFF0C\u907F\u514D\u8207\u524D\u5E7E\u7AE0\u649E\u984C\u3002", "\u6362\u4E00\u79CD\u526F\u7EBF\u7C7B\u578B\u6216\u5199\u6CD5\uFF0C\u907F\u514D\u4E0E\u524D\u51E0\u7AE0\u649E\u9898\u3002", "Change subplot type or treatment to avoid repeating recent chapters.")
      }
    ];
  }
  if (reason === HITL_REASON.DRAFT_LOOP) {
    return [
      {
        id: "draft",
        title: pick("\u76F4\u63A5\u4FEE\u6539\u7AE0\u7BC0\u5167\u6587", "\u76F4\u63A5\u4FEE\u6539\u7AE0\u8282\u6B63\u6587", "Edit Chapter Draft Directly"),
        blurb: pick("\u5728\u4E0B\u65B9\u7DE8\u8F2F\u6B63\u6587\uFF0C\u518D\u5F9E\u9069\u7576\u6B65\u9A5F\u7E8C\u8DD1\u3002", "\u5728\u4E0B\u65B9\u7F16\u8F91\u6B63\u6587\uFF0C\u518D\u4ECE\u5408\u9002\u6B65\u9AA4\u7EED\u8DD1\u3002", "Edit draft below, then resume from the proper step.")
      }
    ];
  }
  if (reason === HITL_REASON.EXTRACTION_GATE) {
    return [
      {
        id: "remap",
        title: pick("\u5C0D\u7167\u89D2\u8272\u8207\u9053\u5177\u540D\u7A31", "\u5BF9\u7167\u89D2\u8272\u4E0E\u9053\u5177\u540D\u79F0", "Map Character and Item Names"),
        blurb: pick(
          "\u4F9D\u7CFB\u7D71\u731C\u6E2C\u4FEE\u6B63\u300C\u6587\u4E2D\u8AAA\u6CD5\u300D\u5C0D\u61C9\u5230\u300C\u8A2D\u5B9A\u8868\u300D\u7684\u54EA\u4E00\u7B46\u3002",
          "\u6309\u7CFB\u7EDF\u731C\u6D4B\u4FEE\u6B63\u201C\u6587\u4E2D\u8BF4\u6CD5\u201D\u5BF9\u5E94\u5230\u201C\u8BBE\u5B9A\u8868\u201D\u7684\u54EA\u4E00\u7B14\u3002",
          "Fix mapping from in-text mentions to canonical records."
        )
      }
    ];
  }
  if (reason === HITL_REASON.B_STORY) {
    return [
      {
        id: "b_story",
        title: pick("\u526F\u7DDA\u662F\u5426\u5DF2\u6536\u5C3E", "\u526F\u7EBF\u662F\u5426\u5DF2\u6536\u5C3E", "Decide Subplot Resolution"),
        blurb: pick("\u6C7A\u5B9A\u6838\u92B7\u526F\u7DDA\u6216\u6253\u56DE\u524D\u6BB5\u6D41\u7A0B\u3002", "\u51B3\u5B9A\u6838\u9500\u526F\u7EBF\u6216\u6253\u56DE\u524D\u6BB5\u6D41\u7A0B\u3002", "Mark subplot as resolved or send flow back.")
      }
    ];
  }
  if (reason === HITL_REASON.CONTEXT) {
    return [
      {
        id: "prune",
        title: pick("\u7CBE\u7C21\u53C3\u8003\u8CC7\u6599", "\u7CBE\u7B80\u53C2\u8003\u8D44\u6599", "Prune Context"),
        blurb: pick("\u522A\u77ED\u5404\u6BB5\u80CC\u666F\u6587\u5B57\uFF0C\u964D\u4F4E\u4E00\u6B21\u8F09\u5165\u91CF\u3002", "\u5220\u77ED\u5404\u6BB5\u80CC\u666F\u6587\u5B57\uFF0C\u964D\u4F4E\u4E00\u6B21\u8F7D\u5165\u91CF\u3002", "Trim context blocks to reduce prompt size.")
      }
    ];
  }
  return [];
}
function defaultSolutionForReason(reason) {
  const list = solutionsForReason(reason);
  return list[0]?.id ?? "outline";
}
var HITL_REASON_MATRIX = [
  {
    reason: HITL_REASON.PLAN_LOOP,
    title: getSituationCopy(HITL_REASON.PLAN_LOOP).title,
    defaultSolution: "outline",
    solutionIds: ["outline", "director"],
    optionIds: ["allow_adjust_anchor", "force_rewrite_plan", "force_approve_plan"]
  },
  {
    reason: HITL_REASON.RESOLUTION_TACTIC,
    title: getSituationCopy(HITL_REASON.RESOLUTION_TACTIC).title,
    defaultSolution: "outline",
    solutionIds: ["outline", "director"],
    optionIds: []
  },
  {
    reason: HITL_REASON.ENDING_VIBE,
    title: getSituationCopy(HITL_REASON.ENDING_VIBE).title,
    defaultSolution: "outline",
    solutionIds: ["outline", "director"],
    optionIds: []
  },
  {
    reason: HITL_REASON.B_STORY_COOLDOWN,
    title: getSituationCopy(HITL_REASON.B_STORY_COOLDOWN).title,
    defaultSolution: "director",
    solutionIds: ["director"],
    optionIds: []
  },
  {
    reason: HITL_REASON.DRAFT_LOOP,
    title: getSituationCopy(HITL_REASON.DRAFT_LOOP).title,
    defaultSolution: "draft",
    solutionIds: ["draft"],
    optionIds: ["keep_current_logic", "relax_word_count"]
  },
  {
    reason: HITL_REASON.EXTRACTION_GATE,
    title: getSituationCopy(HITL_REASON.EXTRACTION_GATE).title,
    defaultSolution: "remap",
    solutionIds: ["remap"],
    optionIds: ["extraction_return_author"]
  },
  {
    reason: HITL_REASON.B_STORY,
    title: getSituationCopy(HITL_REASON.B_STORY).title,
    defaultSolution: "b_story",
    solutionIds: ["b_story"],
    optionIds: ["b_story_wait_judgement"]
  },
  {
    reason: HITL_REASON.CONTEXT,
    title: getSituationCopy(HITL_REASON.CONTEXT).title,
    defaultSolution: "prune",
    solutionIds: ["prune"],
    optionIds: []
  },
  {
    reason: HITL_REASON.ALIGNMENT_RULES_REQUIRED,
    title: getSituationCopy(HITL_REASON.ALIGNMENT_RULES_REQUIRED).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: []
  },
  {
    reason: HITL_REASON.OUTPUT_LANGUAGE,
    title: getSituationCopy(HITL_REASON.OUTPUT_LANGUAGE).title,
    defaultSolution: null,
    solutionIds: [],
    optionIds: ["language_return_author", "language_force_continue"]
  }
];

// src/features/ui-copy/workflowDisplay.ts
function pick2(zhHant2, zhHans2, en) {
  const locale = getRuntimeLocale();
  if (locale === "en") return en;
  if (locale === "zh-Hans") return zhHans2;
  return zhHant2;
}
var RUN_STATUS_LABELS = {
  IDLE: pick2("\u5F85\u958B\u59CB", "\u5F85\u5F00\u59CB", "Idle"),
  RUNNING: pick2("\u9032\u884C\u4E2D", "\u8FDB\u884C\u4E2D", "Running"),
  WAITING_HITL: pick2("\u7B49\u5F85\u60A8\u8655\u7406", "\u7B49\u5F85\u4F60\u5904\u7406", "Waiting for you"),
  COMPLETED: pick2("\u5DF2\u5B8C\u6210", "\u5DF2\u5B8C\u6210", "Completed"),
  FAILED: pick2("\u5931\u6557", "\u5931\u8D25", "Failed")
};
var AGENT_EXTRA = {
  hitl: pick2("\u7B49\u5F85\u60A8\u5354\u52A9", "\u7B49\u5F85\u4F60\u534F\u52A9", "Waiting for your input"),
  chapter_summarizer: pick2("\u6574\u7406\u7AE0\u7BC0\u6458\u8981", "\u6574\u7406\u7AE0\u8282\u6458\u8981", "Summarizing chapter"),
  end: pick2("\u7D50\u675F", "\u7ED3\u675F", "End"),
  END: pick2("\u7D50\u675F", "\u7ED3\u675F", "End")
};
var CHAPTER_STATUS_LABELS = {
  completed: pick2("\u5DF2\u5B8C\u6210", "\u5DF2\u5B8C\u6210", "Completed"),
  draft: pick2("\u8349\u7A3F", "\u8349\u7A3F", "Draft"),
  in_progress: pick2("\u64B0\u5BEB\u4E2D", "\u64B0\u5199\u4E2D", "In Progress"),
  pending: pick2("\u5F85\u8655\u7406", "\u5F85\u5904\u7406", "Pending"),
  published: pick2("\u5DF2\u767C\u4F48", "\u5DF2\u53D1\u5E03", "Published")
};
var DECISION_MODE_LABELS = {
  NONE: pick2("\u7121", "\u65E0", "None"),
  DASHBOARD: pick2("\u53EF\u4E00\u9375\u9078\u64C7", "\u53EF\u4E00\u952E\u9009\u62E9", "One-click options"),
  MANUAL_EDIT: pick2("\u9700\u586B\u5BEB\u8868\u55AE", "\u9700\u586B\u5199\u8868\u5355", "Manual form"),
  STATE_INJECTION: pick2("\u9032\u968E\u5BEB\u5165", "\u8FDB\u9636\u5199\u5165", "Advanced injection")
};
function hitlDecisionModeLabel(mode) {
  const m = mode.trim();
  if (!m) return "\u2014";
  return DECISION_MODE_LABELS[m] ?? pick2(`\u6A21\u5F0F\uFF1A${m}`, `\u6A21\u5F0F\uFF1A${m}`, `Mode: ${m}`);
}
var ROUTE_DECISION_LABELS = {
  pause: pick2("\u66AB\u505C", "\u6682\u505C", "Pause"),
  hitl: pick2("\u7B49\u5F85\u5354\u52A9", "\u7B49\u5F85\u534F\u52A9", "Await help"),
  planner: pick2("\u56DE\u5230\u5287\u60C5\u898F\u5283", "\u56DE\u5230\u5267\u60C5\u89C4\u5212", "Back to planning"),
  author: pick2("\u56DE\u5230\u64B0\u5BEB", "\u56DE\u5230\u64B0\u5199", "Back to writing"),
  reader: pick2("\u95B1\u8B80\u6AA2\u67E5", "\u9605\u8BFB\u68C0\u67E5", "Reader check"),
  extraction_gate: pick2("\u8A2D\u5B9A\u6B78\u6A94", "\u8BBE\u5B9A\u5F52\u6863", "Extraction gate"),
  resolve_subplots: pick2("\u526F\u7DDA\u6536\u5C3E", "\u526F\u7EBF\u6536\u5C3E", "Resolve subplot"),
  state_updater: pick2("\u5B8C\u7A3F\u66F4\u65B0", "\u5B8C\u7A3F\u66F4\u65B0", "State update"),
  graph_rag: pick2("\u80CC\u666F\u6574\u7406", "\u80CC\u666F\u6574\u7406", "Context prep"),
  draft_supervisor: pick2("\u5167\u6587\u5BE9\u6838", "\u6B63\u6587\u5BA1\u6838", "Draft review"),
  plan_supervisor: pick2("\u5927\u7DB1\u5BE9\u6838", "\u5927\u7EB2\u5BA1\u6838", "Plan review"),
  director: pick2("\u7AE0\u7BC0\u65B9\u5411", "\u7AE0\u8282\u65B9\u5411", "Chapter direction"),
  b_story_resolve: pick2("\u526F\u7DDA\u6536\u5C3E", "\u526F\u7EBF\u6536\u5C3E", "Resolve subplot"),
  "": "\u2014"
};

// src/features/hitl-panel/hitlNarrative.ts
function asRecord2(v) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : null;
}
function mapHitlQuickActionLabel(optionId, serverLabel, t) {
  const key = `hitl.option.${optionId}`;
  const v = t(key, "");
  if (v.trim() && v !== key) return v;
  const s = String(serverLabel ?? "").trim();
  return s || optionId;
}
function mapHitlOptionHint(optionId, t) {
  const key = `hitl.hint.${optionId}`;
  return t(key, "");
}
function buildPlanLoopFailureLine(state, t) {
  const pf = state.plan_feedback;
  if (!Array.isArray(pf) || pf.length === 0) return null;
  const last = pf[pf.length - 1];
  const row = asRecord2(last);
  if (!row) return null;
  const msg = String(row.message ?? "").trim();
  if (msg) return `${t("hitl.planLoop.failurePrefix", "\u7121\u6CD5\u901A\u904E\u539F\u56E0")}\uFF1A${msg}`;
  const viol = String(row.violation ?? "").trim();
  if (viol) return `${t("hitl.planLoop.failurePrefix", "\u7121\u6CD5\u901A\u904E\u539F\u56E0")}\uFF1A${viol}`;
  return null;
}
function lastResolutionMethod(state) {
  const rows = state.recent_chapter_summaries;
  if (!Array.isArray(rows) || rows.length === 0) return "";
  const last = rows[rows.length - 1];
  const r = asRecord2(last);
  return String(r?.resolution_method ?? "").trim();
}
function lastEndingVibe(state) {
  const rows = state.recent_chapter_summaries;
  if (!Array.isArray(rows) || rows.length === 0) return "";
  const last = rows[rows.length - 1];
  const r = asRecord2(last);
  return String(r?.ending_vibe ?? "").trim();
}
function buildHitlPrimaryHeadline(reason, state, hitlContext, t) {
  switch (reason) {
    case HITL_REASON.PLAN_LOOP:
      return { headline: t("hitl.planLoop.headline"), extraLine: buildPlanLoopFailureLine(state, t) };
    case HITL_REASON.RESOLUTION_TACTIC: {
      const tactic = lastResolutionMethod(state) || t("hitl.resolutionTactic.tacticFallback");
      return { headline: t("hitl.resolutionTactic.headline", "", { tactic }), extraLine: null };
    }
    case HITL_REASON.ENDING_VIBE: {
      const vibe = lastEndingVibe(state) || t("hitl.endingVibe.vibeFallback");
      return { headline: t("hitl.endingVibe.headline", "", { vibe }), extraLine: null };
    }
    case HITL_REASON.B_STORY_COOLDOWN: {
      const name = pickBStoryCooldownName(state) || t("hitl.bStoryCooldown.nameFallback");
      const n = String(estimateBStoryStagnantChapters(state));
      return { headline: t("hitl.bStoryCooldown.headline", "", { name, n }), extraLine: null };
    }
    case HITL_REASON.DRAFT_LOOP:
      return { headline: t("hitl.draftLoop.headline"), extraLine: null };
    case HITL_REASON.OUTPUT_LANGUAGE:
      return { headline: t("hitl.outputLanguage.headline"), extraLine: null };
    case HITL_REASON.EXTRACTION_GATE:
      return { headline: t("hitl.extraction.headline"), extraLine: buildExtractionEntityLine(state, t) };
    case HITL_REASON.B_STORY: {
      const cand = asRecord2(state.b_story_resolution_hitl_candidate);
      const name = cand && (String(cand.subplot_title ?? cand.title ?? cand.name ?? "").trim() || String(cand.id ?? "").trim()) || t("hitl.bStoryResolve.nameFallback");
      return { headline: t("hitl.bStoryResolve.headline", "", { name }), extraLine: null };
    }
    case HITL_REASON.CONTEXT: {
      const est = state.context_overflow_char_estimate;
      const n = est != null && Number.isFinite(Number(est)) ? String(est) : "\u2014";
      return {
        headline: t("hitl.context.headline"),
        extraLine: t("hitl.context.estimate", "", { n })
      };
    }
    case HITL_REASON.ALIGNMENT_RULES_REQUIRED: {
      const issue = String(hitlContext?.primary_issue ?? "").trim() || String(state.alignment_log ?? "").trim().slice(0, 120) || t("hitl.alignment.issueFallback");
      return { headline: t("hitl.alignment.headline", "", { issue }), extraLine: null };
    }
    default:
      return { headline: t("hitl.title"), extraLine: null };
  }
}
function pickBStoryCooldownName(state) {
  const chosen = String(state.b_story_type ?? "").trim().toUpperCase();
  const stories = state.active_b_stories;
  if (Array.isArray(stories) && chosen) {
    for (const row of stories) {
      const r = asRecord2(row);
      if (!r) continue;
      const typ = String(r.type ?? "").trim().toUpperCase();
      if (typ === chosen) {
        const id = String(r.id ?? "").trim();
        const desc = String(r.desc ?? "").trim();
        if (desc) return desc.slice(0, 80);
        if (id) return id;
      }
    }
  }
  const dir = String(state.b_story_directive ?? "").trim();
  if (dir) return dir.slice(0, 80);
  return "";
}
function estimateBStoryStagnantChapters(state) {
  const recent = state.recent_b_story_types;
  if (Array.isArray(recent) && recent.length > 0) return Math.min(12, recent.length + 2);
  return 3;
}
function buildExtractionEntityLine(state, t) {
  const hints = state.hitl_extraction_remap_hints;
  if (!Array.isArray(hints) || hints.length === 0) return null;
  const names = [];
  for (const h of hints.slice(0, 3)) {
    const r = asRecord2(h);
    if (!r) continue;
    const pname = String(r.planned_canonical_name ?? "").trim();
    const mid = String(r.missing_planned_node_id ?? "").trim();
    const label = pname || mid;
    if (label) names.push(label);
  }
  if (!names.length) return null;
  return t("hitl.extraction.entitiesPrefix", "", { names: names.join("\u3001") });
}
function getRemapExpectedNodeType(missingPlannedNodeId, state) {
  const id = missingPlannedNodeId.trim();
  if (!id) return null;
  const planned = state.planned_graph_nodes;
  if (!Array.isArray(planned)) return null;
  for (const row of planned) {
    const r = asRecord2(row);
    if (!r) continue;
    if (String(r.node_id ?? "").trim() === id) {
      const nt = r.node_type;
      return nt != null && String(nt).trim() ? String(nt).trim() : null;
    }
  }
  return null;
}
function parseExtractionRemapHints(hints) {
  if (!Array.isArray(hints)) return [];
  const out = [];
  for (const h of hints) {
    const r = asRecord2(h);
    if (!r) continue;
    const mid = String(r.missing_planned_node_id ?? "").trim();
    const pname = String(r.planned_canonical_name ?? "").trim();
    const candidates = Array.isArray(r.candidate_extracted) ? r.candidate_extracted : [];
    const fromOptions = [];
    for (const c of candidates) {
      const cc = asRecord2(c);
      if (!cc) continue;
      const nid = String(cc.node_id ?? "").trim();
      const cn = String(cc.canonical_name ?? "").trim();
      if (!nid) continue;
      fromOptions.push({ node_id: nid, label: cn ? `${cn} (${nid})` : nid });
    }
    if (!mid && fromOptions.length === 0) continue;
    out.push({
      missing_planned_node_id: mid,
      planned_canonical_name: pname,
      fromOptions,
      defaultFromId: fromOptions[0]?.node_id ?? ""
    });
  }
  return out;
}
function filterGraphNodesByType(nodes, nodeType) {
  if (!nodeType) return nodes;
  const t = nodeType.trim().toUpperCase();
  return nodes.filter((n) => String(n.node_type ?? "").trim().toUpperCase() === t);
}

// src/features/hitl-panel/HitlPanel.tsx
import { Fragment, jsx as jsx2, jsxs } from "react/jsx-runtime";
function isHitlActive(workflow) {
  if (!workflow) return false;
  const st = workflow.state;
  return workflow.run.requires_hitl === true || workflow.run.status === "WAITING_HITL" || st.workflow_status === "WAITING_HITL";
}
var asyncNoop = async () => {
};
var formSchema = z.object({
  narrativeScript: z.string().default(""),
  outlineEvents: z.array(
    z.object({
      event_id: z.string().trim().min(1, "event_id required"),
      description: z.string().trim().min(1, "description required"),
      caused_by_event_id: z.string().trim().optional()
    })
  ).default([]),
  draftText: z.string().default(""),
  draftResumeFrom: z.string().default("reader"),
  mergeHintsOnDraft: z.boolean().default(false),
  chapterType: z.string().default(""),
  bStoryDirective: z.string().default(""),
  bStoryType: z.string().default(""),
  newElementsLines: z.string().default(""),
  narrativeDirective: z.string().default(""),
  anchorId: z.string().default(""),
  anchorChapterInput: z.string().default("1"),
  bResolved: z.array(z.string()).default([]),
  bEvidence: z.array(z.string()).default([]),
  bAnalysis: z.string().default(""),
  bRejectResume: z.string().default("extraction_gate"),
  pruneProductTier: z.number().min(0).max(2).default(0),
  alignmentRulesInput: z.string().default(""),
  pacingLimitInput: z.string().default(""),
  futureAnchorTitle: z.string().default(""),
  futureAnchorDesc: z.string().default(""),
  futureAnchorDelay: z.string().default(""),
  remaps: z.array(
    z.object({
      from_node_id: z.string().trim(),
      to_node_id: z.string().trim()
    })
  ).default([]),
  waiveIdsComma: z.string().default(""),
  injectionJson: z.string().default("[]"),
  advancedInjectAck: z.boolean().default(false),
  directorNotes: z.string().default(""),
  bRejectNote: z.string().default("")
});
function HitlPanel({
  workflow,
  graph: graphProp = null,
  storyId = null,
  variant = "default",
  busy = false,
  workflowError = "",
  onDecision,
  onOutlineEdit,
  onStateInjection,
  onDraftEdit,
  onDirectorPatch = asyncNoop,
  onExtractionRemap = asyncNoop,
  onBStoryJudgement = asyncNoop,
  onAnchorDelay = asyncNoop,
  onContextPrune = asyncNoop
}) {
  const { t } = useI18n();
  const [remapMissingIds, setRemapMissingIds] = useState2([]);
  const [localGraph, setLocalGraph] = useState2(null);
  const [graphLoading, setGraphLoading] = useState2(false);
  const [bStoryRejectOpen, setBStoryRejectOpen] = useState2(false);
  const [preview, setPreview] = useState2(null);
  const [selectedSolution, setSelectedSolution] = useState2(null);
  const [advancedOpen, setAdvancedOpen] = useState2(false);
  const [uiMode, setUiMode] = useState2("recommended");
  const [tokenInput, setTokenInput] = useState2("");
  const [tokenInputEvidence, setTokenInputEvidence] = useState2("");
  const form = useForm({
    resolver: zodResolver(formSchema),
    mode: "onChange",
    defaultValues: {
      narrativeScript: "",
      outlineEvents: [{ event_id: "event_01", description: "", caused_by_event_id: "" }],
      draftText: "",
      draftResumeFrom: "reader",
      mergeHintsOnDraft: false,
      chapterType: "",
      bStoryDirective: "",
      bStoryType: "",
      newElementsLines: "",
      narrativeDirective: "",
      anchorId: "",
      anchorChapterInput: "1",
      bResolved: [],
      bEvidence: [],
      bAnalysis: "",
      bRejectResume: "author",
      pruneProductTier: 0,
      alignmentRulesInput: "",
      pacingLimitInput: "",
      futureAnchorTitle: "",
      futureAnchorDesc: "",
      futureAnchorDelay: "",
      remaps: [{ from_node_id: "ghost_01", to_node_id: "planned_01" }],
      waiveIdsComma: "",
      injectionJson: '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"backup_item","description":"HITL injected"}}]',
      advancedInjectAck: false,
      directorNotes: "",
      bRejectNote: ""
    }
  });
  const { register, watch, setValue, getValues, formState } = form;
  const outlineArray = useFieldArray({ control: form.control, name: "outlineEvents" });
  const remapArray = useFieldArray({ control: form.control, name: "remaps" });
  const hitlActive = isHitlActive(workflow);
  const controlsLocked = !hitlActive || busy;
  const hitlContext = workflow?.run.hitl_context ?? null;
  const rawOptions = workflow?.state.pending_hitl_options ?? [];
  const options = useMemo2(
    () => rawOptions.filter((o) => o.id !== "b_story_wait_judgement"),
    [rawOptions]
  );
  const reason = String(workflow?.run.hitl_reason ?? workflow?.state.hitl_reason ?? "");
  const resumeHint = String(workflow?.state.resume_from ?? "");
  const compact = variant === "compact";
  const primaryNarrative = useMemo2(() => {
    if (!workflow?.state) return { headline: t("hitl.title"), extraLine: null };
    return buildHitlPrimaryHeadline(reason, workflow.state, hitlContext, t);
  }, [reason, workflow?.state, hitlContext, t]);
  const feedbackLines = useMemo2(() => {
    if (!workflow?.state) return [];
    if (reason === HITL_REASON.PLAN_LOOP && primaryNarrative.extraLine) return [];
    return buildFeedbackSummary(workflow.state, reason);
  }, [workflow?.state, reason, primaryNarrative.extraLine]);
  const solutionList = useMemo2(() => solutionsForReason(reason), [reason]);
  const bAnalysisWatch = useWatch({ control: form.control, name: "bAnalysis", defaultValue: "" });
  const bStoryDisplay = useMemo2(() => formatBStoryCandidateForDisplay(String(bAnalysisWatch ?? "")), [bAnalysisWatch]);
  const effectiveGraph = graphProp && graphProp.nodes.length > 0 ? graphProp : localGraph;
  const extractionModels = useMemo2(
    () => parseExtractionRemapHints(workflow?.state?.hitl_extraction_remap_hints),
    [workflow?.state?.hitl_extraction_remap_hints]
  );
  useEffect(() => {
    if (!hitlActive || reason !== HITL_REASON.EXTRACTION_GATE || !storyId?.trim()) return;
    if (graphProp && graphProp.nodes.length > 0) return;
    if (localGraph && localGraph.nodes.length > 0) return;
    let cancelled = false;
    setGraphLoading(true);
    void fetchGraph(storyId.trim()).then((g) => {
      if (!cancelled) setLocalGraph(g);
    }).catch(() => {
      if (!cancelled) setLocalGraph(null);
    }).finally(() => {
      if (!cancelled) setGraphLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [hitlActive, reason, storyId, graphProp, localGraph]);
  useEffect(() => {
    if (!hitlActive) return;
    const list = solutionsForReason(reason);
    setSelectedSolution(list.length ? defaultSolutionForReason(reason) : null);
  }, [hitlActive, reason, workflow?.run.run_id]);
  useEffect(() => {
    if (hitlActive && workflow?.state.current_draft != null) {
      setValue("draftText", String(workflow.state.current_draft));
    }
  }, [hitlActive, workflow?.run.run_id, workflow?.state.current_draft]);
  useEffect(() => {
    if (!hitlActive || !workflow?.state) return;
    const st = workflow.state;
    if (isPlanFamilyReason(reason)) {
      const gt = st.ground_truth_events;
      if (Array.isArray(gt) && gt.length > 0) {
        const mapped = gt.map((row, i) => ({
          event_id: String(row.event_id ?? "").trim() || `event_${i + 1}`,
          description: String(row.description ?? "").trim(),
          caused_by_event_id: row.caused_by_event_id != null ? String(row.caused_by_event_id).trim() : ""
        }));
        outlineArray.replace(mapped);
      }
      setValue("narrativeScript", String(st.narrative_script ?? ""));
    }
    if (isDirectorPatchReason(reason)) {
      const anchors = st.unachieved_anchors ?? [];
      const first = anchors[0]?.anchor_id;
      if (first) setValue("anchorId", String(first));
      const cid = Number(st.chapter_id ?? 1);
      setValue("anchorChapterInput", String(cid + 1));
      if (reason === HITL_REASON.B_STORY_COOLDOWN) {
        setValue("directorNotes", String(st.b_story_directive ?? ""));
      } else {
        setValue("directorNotes", String(st.narrative_directive ?? ""));
      }
    }
    if (reason === HITL_REASON.EXTRACTION_GATE) {
      const h = st.hitl_extraction_remap_hints;
      const models = parseExtractionRemapHints(h);
      setRemapMissingIds(models.map((m) => m.missing_planned_node_id));
      const rows = models.map((m) => ({ from_node_id: m.defaultFromId, to_node_id: "" }));
      if (rows.length) {
        remapArray.replace(rows);
      } else {
        setRemapMissingIds([]);
        remapArray.replace([{ from_node_id: "", to_node_id: "" }]);
      }
    }
    if (reason === HITL_REASON.B_STORY) {
      setBStoryRejectOpen(false);
      setValue("bRejectNote", "");
      const cand = st.b_story_resolution_hitl_candidate;
      if (cand && typeof cand === "object") {
        setValue("bAnalysis", JSON.stringify(cand, null, 2));
        const c = cand;
        const suggestedB = Array.isArray(c.suggested_resolved_b_stories) ? c.suggested_resolved_b_stories : [];
        const suggestedE = Array.isArray(c.suggested_resolution_evidence_event_ids) ? c.suggested_resolution_evidence_event_ids : [];
        setValue(
          "bResolved",
          suggestedB.map((x) => String(x).trim()).filter(Boolean)
        );
        setValue(
          "bEvidence",
          suggestedE.map((x) => String(x).trim()).filter(Boolean)
        );
      }
    }
    if (reason === HITL_REASON.CONTEXT) {
      const meta = workflow?.run.hitl_context?.context_metadata;
      const suggested = meta?.graph_rag_context_tier;
      if (typeof suggested === "number" && suggested >= 0 && suggested <= 2) {
        setValue("pruneProductTier", suggested);
      } else {
        setValue("pruneProductTier", 0);
      }
    }
    if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) {
      setValue("alignmentRulesInput", String(st.chapter_hard_rules ?? ""));
    }
  }, [hitlActive, reason, workflow?.run.run_id, workflow?.run.hitl_context, workflow?.state, remapArray, outlineArray, setValue]);
  useEffect(() => {
    if (!hitlActive) {
      setUiMode("recommended");
    }
  }, [hitlActive, workflow?.run.run_id]);
  const shell = compact ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow" : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";
  const inputClass = compact ? "auteur-input mt-1 text-xs" : "auteur-input mt-1 text-sm";
  const btnClass = "btn-secondary mt-2 w-full text-xs";
  const taRows = (n) => compact ? Math.max(3, n - 2) : n;
  const waiveList = () => String(getValues("waiveIdsComma") ?? "").split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
  const decisionMode = String(workflow?.run.hitl_decision_mode ?? "");
  return /* @__PURE__ */ jsxs("section", { className: shell, children: [
    /* @__PURE__ */ jsxs("div", { className: "mb-2 flex flex-wrap items-center justify-between gap-2", children: [
      /* @__PURE__ */ jsx2("h2", { className: "font-headline text-sm font-bold uppercase tracking-wider text-tertiary", children: t("hitl.title") }),
      hitlActive ? /* @__PURE__ */ jsx2(
        "button",
        {
          type: "button",
          className: "shrink-0 rounded-md border border-error/50 bg-error/15 px-2 py-1 font-label text-[11px] font-semibold text-error hover:bg-error/25 disabled:opacity-40",
          disabled: controlsLocked,
          onClick: () => onDecision("ABORT_AND_RESTART"),
          children: t("hitl.abortChapter")
        }
      ) : null
    ] }),
    /* @__PURE__ */ jsx2("p", { className: "mb-3 font-body text-sm text-on-surface-variant", children: hitlActive ? /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx2("strong", { className: "text-tertiary", children: t("hitl.workflowPaused") }),
      /* @__PURE__ */ jsxs("span", { className: "text-on-surface-variant", children: [
        " ",
        "\xB7 ",
        hitlDecisionModeLabel(decisionMode)
      ] })
    ] }) : t("hitl.noPending") }),
    hitlActive ? /* @__PURE__ */ jsxs(
      "div",
      {
        className: "mb-3 inline-flex rounded-lg border border-outline-variant/25 bg-surface-container-highest/30 p-1",
        role: "tablist",
        "aria-label": t("hitl.modeSwitchAria"),
        children: [
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              id: "hitl-mode-recommended",
              role: "tab",
              "aria-controls": "hitl-mode-panel",
              "aria-selected": uiMode === "recommended",
              className: `rounded-md px-3 py-1 text-xs ${uiMode === "recommended" ? "bg-primary/20 text-primary" : "text-on-surface-variant"}`,
              disabled: controlsLocked,
              onClick: () => setUiMode("recommended"),
              children: t("hitl.modeRecommended")
            }
          ),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              id: "hitl-mode-expert",
              role: "tab",
              "aria-controls": "hitl-mode-panel",
              "aria-selected": uiMode === "expert",
              className: `rounded-md px-3 py-1 text-xs ${uiMode === "expert" ? "bg-secondary/20 text-secondary" : "text-on-surface-variant"}`,
              disabled: controlsLocked,
              onClick: () => setUiMode("expert"),
              children: t("hitl.modeExpert")
            }
          )
        ]
      }
    ) : null,
    hitlActive ? /* @__PURE__ */ jsxs(Fragment, { children: [
      workflowError.trim() ? /* @__PURE__ */ jsx2("div", { className: "mb-3 rounded-lg border border-error/40 bg-error/10 px-3 py-2 font-body text-sm text-error", children: workflowError.trim() }) : null,
      /* @__PURE__ */ jsxs("div", { className: "mb-4 rounded-lg border border-tertiary/20 bg-tertiary/5 px-3 py-3", children: [
        /* @__PURE__ */ jsx2("h3", { className: "font-headline text-sm font-bold text-on-surface", children: primaryNarrative.headline }),
        primaryNarrative.extraLine ? /* @__PURE__ */ jsx2("p", { className: "mt-2 font-body text-sm leading-relaxed text-on-surface", children: primaryNarrative.extraLine }) : null,
        hitlContext?.primary_issue && reason !== HITL_REASON.ALIGNMENT_RULES_REQUIRED ? /* @__PURE__ */ jsx2("p", { className: "mt-2 rounded-md bg-surface-container-highest/60 px-2 py-2 font-body text-xs text-on-surface", children: hitlContext.primary_issue }) : null,
        hitlContext?.context_metadata?.payload_type === "output_language" && hitlContext.context_metadata.expected_output_language ? /* @__PURE__ */ jsxs("p", { className: "mt-2 font-label text-xs text-on-surface-variant", children: [
          t("hitl.outputLanguage.projectLang"),
          /* @__PURE__ */ jsx2("span", { className: "text-on-surface", children: String(hitlContext.context_metadata.expected_output_language) })
        ] }) : null,
        hitlContext?.context_metadata?.language_detection_summary ? /* @__PURE__ */ jsx2("p", { className: "mt-1 font-body text-xs text-on-surface-variant", children: hitlContext.context_metadata.language_detection_summary }) : null,
        /* @__PURE__ */ jsx2("p", { className: "mt-2 font-label text-xs text-on-surface-variant", children: t("hitl.resumeNear", "", { step: resumeNodeUserLabel(resumeHint) }) })
      ] }),
      feedbackLines.length > 0 ? /* @__PURE__ */ jsxs("div", { className: "mb-4 rounded-lg bg-surface-container-highest/50 px-3 py-2", children: [
        /* @__PURE__ */ jsx2("p", { className: "font-label text-[10px] uppercase tracking-wider text-on-surface-variant", children: t("hitl.systemFeedback") }),
        /* @__PURE__ */ jsx2("ul", { className: "mt-1 list-inside list-disc font-body text-sm text-on-surface", children: feedbackLines.map((line, i) => /* @__PURE__ */ jsx2("li", { children: line }, i)) })
      ] }) : null,
      reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED ? /* @__PURE__ */ jsxs("div", { className: "mb-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-3", "aria-live": "polite", children: [
        /* @__PURE__ */ jsx2(
          "textarea",
          {
            className: inputClass,
            rows: taRows(8),
            disabled: controlsLocked,
            placeholder: t("hitl.alignment.placeholder"),
            ...register("alignmentRulesInput")
          }
        ),
        !watch("alignmentRulesInput").trim() ? /* @__PURE__ */ jsx2("p", { className: "mt-1 font-body text-xs text-error", children: t("hitl.alignment.required") }) : null,
        /* @__PURE__ */ jsx2(
          "button",
          {
            type: "button",
            className: btnClass,
            disabled: controlsLocked || !watch("alignmentRulesInput").trim(),
            onClick: () => {
              if (!watch("alignmentRulesInput").trim()) return;
              onStateInjection({
                mutations: [],
                chapter_hard_rules: watch("alignmentRulesInput"),
                resume_from: "logic_alignment",
                reason: "alignment_rules_patch",
                this_chapter_pacing_limit: "",
                future_anchor_title: "",
                future_anchor_description: "",
                chapters_to_delay: null
              });
            },
            children: t("hitl.alignment.submit")
          }
        )
      ] }) : null,
      options.length > 0 ? /* @__PURE__ */ jsxs("div", { className: "mb-4", children: [
        /* @__PURE__ */ jsx2("p", { className: "mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant", children: t("hitl.quickActions") }),
        /* @__PURE__ */ jsx2("div", { className: "flex flex-col gap-2", children: options.map((option) => /* @__PURE__ */ jsxs("div", { className: "rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 p-2", children: [
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              disabled: controlsLocked,
              onClick: () => {
                if (option.id === "force_approve_plan") {
                  setPreview({
                    title: t("hitl.preview.forceApproveTitle"),
                    bullets: [t("hitl.preview.forceApproveBullet1"), t("hitl.preview.forceApproveBullet2")],
                    confirmLabel: t("hitl.preview.forceApproveConfirm"),
                    onConfirm: () => void onDecision(option.id)
                  });
                  return;
                }
                void onDecision(option.id);
              },
              className: "w-full rounded-md bg-primary/15 px-3 py-2 text-left font-label text-sm font-medium text-primary transition-colors hover:bg-primary/25 disabled:opacity-40",
              children: mapHitlQuickActionLabel(option.id, option.label, t)
            }
          ),
          mapHitlOptionHint(option.id, t).trim() ? /* @__PURE__ */ jsx2("p", { className: "mt-1.5 px-1 font-body text-xs text-on-surface-variant", children: mapHitlOptionHint(option.id, t) }) : null
        ] }, option.id)) })
      ] }) : null,
      reason === HITL_REASON.PLAN_LOOP ? /* @__PURE__ */ jsxs("div", { className: "mb-4 rounded-lg border border-outline-variant/20 bg-surface-container-highest/30 px-3 py-3", children: [
        /* @__PURE__ */ jsx2("h4", { className: "font-headline text-xs font-bold text-on-surface", children: t("hitl.anchor.sectionTitle") }),
        /* @__PURE__ */ jsx2("p", { className: "mt-1 font-body text-xs text-on-surface-variant", children: t("hitl.anchor.hint") }),
        /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.anchor.id") }),
        /* @__PURE__ */ jsx2("input", { className: inputClass, disabled: controlsLocked, ...register("anchorId") }),
        /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.anchor.chapter") }),
        /* @__PURE__ */ jsx2("input", { type: "number", min: 1, className: inputClass, disabled: controlsLocked, ...register("anchorChapterInput") }),
        /* @__PURE__ */ jsx2(
          "button",
          {
            type: "button",
            className: btnClass,
            disabled: controlsLocked || !watch("anchorId").trim(),
            onClick: () => {
              const n = Number.parseInt(getValues("anchorChapterInput").trim(), 10);
              if (!Number.isFinite(n) || n < 1) return;
              void onAnchorDelay({ anchor_id: getValues("anchorId").trim(), new_chapter_target: n });
            },
            children: t("hitl.anchor.submit")
          }
        )
      ] }) : null,
      solutionList.length > 0 ? /* @__PURE__ */ jsxs("div", { className: "mb-3", children: [
        /* @__PURE__ */ jsx2("p", { className: "mb-2 font-label text-[10px] uppercase tracking-wider text-on-surface-variant", children: t("hitl.chooseSolution") }),
        /* @__PURE__ */ jsx2("div", { className: `flex flex-wrap gap-2 ${compact ? "" : "gap-3"}`, children: solutionList.map((sol) => /* @__PURE__ */ jsxs(
          "button",
          {
            type: "button",
            disabled: controlsLocked,
            onClick: () => setSelectedSolution(sol.id),
            className: `max-w-full rounded-xl border px-3 py-2 text-left transition-colors ${selectedSolution === sol.id ? "border-tertiary bg-tertiary/15 ring-1 ring-tertiary/30" : "border-outline-variant/20 bg-surface-container-highest/40 hover:border-outline-variant/40"} disabled:opacity-40`,
            children: [
              /* @__PURE__ */ jsx2("span", { className: "block font-label text-sm font-semibold text-on-surface", children: sol.title }),
              /* @__PURE__ */ jsx2("span", { className: "mt-0.5 block font-body text-xs text-on-surface-variant", children: sol.blurb })
            ]
          },
          sol.id
        )) })
      ] }) : null,
      /* @__PURE__ */ jsxs("div", { id: "hitl-mode-panel", role: "tabpanel", "aria-labelledby": uiMode === "recommended" ? "hitl-mode-recommended" : "hitl-mode-expert", className: "rounded-xl border border-outline-variant/15 bg-surface-container-highest/40 p-4", children: [
        selectedSolution === "outline" && isPlanFamilyReason(reason) ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: t("hitl.outline.title") }),
          /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.outline.hint") }),
          /* @__PURE__ */ jsx2("div", { className: "space-y-2", children: outlineArray.fields.map((field, idx) => /* @__PURE__ */ jsxs(
            "div",
            {
              className: "rounded-lg border border-outline-variant/20 bg-surface-container-low p-2",
              draggable: !controlsLocked,
              onDragStart: (e) => e.dataTransfer.setData("text/plain", String(idx)),
              onDragOver: (e) => e.preventDefault(),
              onDrop: (e) => {
                const src = Number.parseInt(e.dataTransfer.getData("text/plain"), 10);
                if (Number.isFinite(src) && src !== idx) outlineArray.move(src, idx);
              },
              children: [
                /* @__PURE__ */ jsxs("div", { className: "flex items-center gap-2", children: [
                  /* @__PURE__ */ jsx2("span", { className: "font-label text-[10px] text-on-surface-variant", children: t("hitl.outline.eventN", "", { n: idx + 1 }) }),
                  /* @__PURE__ */ jsx2("button", { type: "button", className: "btn-secondary ml-auto text-[10px]", disabled: controlsLocked || outlineArray.fields.length <= 1, onClick: () => outlineArray.remove(idx), children: t("hitl.delete") })
                ] }),
                /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-1 text-[10px] text-on-surface-variant", children: t("hitl.outline.eventId") }),
                /* @__PURE__ */ jsx2("input", { className: `${inputClass} font-mono text-xs`, disabled: controlsLocked, ...register(`outlineEvents.${idx}.event_id`) }),
                /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-1", children: t("hitl.outline.description") }),
                /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(4), disabled: controlsLocked, ...register(`outlineEvents.${idx}.description`) }),
                /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-1 text-[10px] text-on-surface-variant", children: t("hitl.outline.causedBy") }),
                /* @__PURE__ */ jsx2("input", { className: inputClass, disabled: controlsLocked, ...register(`outlineEvents.${idx}.caused_by_event_id`) })
              ]
            },
            field.id
          )) }),
          /* @__PURE__ */ jsx2("button", { type: "button", className: btnClass, disabled: controlsLocked, onClick: () => outlineArray.append({ event_id: "", description: "", caused_by_event_id: "" }), children: t("hitl.outline.addCard") }),
          /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.outline.narrativeScript") }),
          /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(3), disabled: controlsLocked, ...register("narrativeScript") }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked || !formState.isValid,
              onClick: () => {
                const nextEvents = getValues("outlineEvents");
                const current = Array.isArray(workflow?.state?.ground_truth_events) ? workflow?.state?.ground_truth_events : [];
                const removed = current.filter((row) => !nextEvents.some((e) => e.event_id === String(row.event_id ?? "")));
                const added = nextEvents.filter((row) => !current.some((e) => String(e.event_id ?? "") === row.event_id));
                setPreview({
                  title: t("hitl.outline.previewTitle"),
                  bullets: [
                    t("hitl.outline.previewStats", "", {
                      added: added.length,
                      removed: removed.length,
                      total: nextEvents.length
                    })
                  ],
                  confirmLabel: t("hitl.outline.previewConfirm"),
                  onConfirm: () => void onOutlineEdit({
                    ground_truth_events: nextEvents,
                    narrative_script: getValues("narrativeScript")
                  })
                });
              },
              children: t("hitl.outline.previewApply")
            }
          )
        ] }) : null,
        selectedSolution === "director" && isDirectorPatchReason(reason) ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: reason === HITL_REASON.B_STORY_COOLDOWN ? t("hitl.director.titleBStory") : t("hitl.director.titlePlan") }),
          /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(6), disabled: controlsLocked, placeholder: t("hitl.director.placeholder"), ...register("directorNotes") }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked,
              onClick: () => {
                const notes = getValues("directorNotes").trim();
                if (reason === HITL_REASON.B_STORY_COOLDOWN) {
                  void onDirectorPatch({ b_story_directive: notes || void 0 });
                } else {
                  void onDirectorPatch({ narrative_directive: notes || void 0 });
                }
              },
              children: t("hitl.director.apply")
            }
          )
        ] }) : null,
        selectedSolution === "draft" && reason === HITL_REASON.DRAFT_LOOP ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: t("hitl.draft.title") }),
          /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.draft.hint") }),
          /* @__PURE__ */ jsxs("label", { className: "flex items-center gap-2 font-label text-xs text-on-surface-variant", children: [
            /* @__PURE__ */ jsx2("input", { type: "checkbox", disabled: controlsLocked, ...register("mergeHintsOnDraft") }),
            t("hitl.draft.mergeHints")
          ] }),
          /* @__PURE__ */ jsx2("label", { className: "auteur-label", children: t("hitl.draft.resumeLabel") }),
          /* @__PURE__ */ jsx2("select", { className: inputClass, disabled: controlsLocked, ...register("draftResumeFrom"), children: DRAFT_RESUME_OPTIONS.map((o) => /* @__PURE__ */ jsx2("option", { value: o.value, children: t(`hitl.draft.resume.${o.value}`, o.label) }, o.value)) }),
          /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(10), disabled: controlsLocked, ...register("draftText") }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked,
              onClick: () => onDraftEdit({
                chapter_content: getValues("draftText"),
                resume_from: getValues("draftResumeFrom"),
                merge_extraction_hints: getValues("mergeHintsOnDraft")
              }),
              children: t("hitl.draft.submit")
            }
          )
        ] }) : null,
        selectedSolution === "remap" && reason === HITL_REASON.EXTRACTION_GATE ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: t("hitl.remap.title") }),
          /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.remap.hint") }),
          graphLoading ? /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.remap.graphLoading") }) : null,
          !graphLoading && (!effectiveGraph || effectiveGraph.nodes.length === 0) ? /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-warning", children: t("hitl.remap.graphEmpty") }) : null,
          extractionModels.length === 0 ? /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.remap.noHints") }) : null,
          /* @__PURE__ */ jsx2("div", { className: "space-y-2", children: remapArray.fields.map((field, idx) => {
            const stObj = workflow?.state;
            const missingId = String(remapMissingIds[idx] ?? "").trim();
            const expectedType = stObj ? getRemapExpectedNodeType(missingId, stObj) : null;
            let rightNodes = filterGraphNodesByType(effectiveGraph?.nodes ?? [], expectedType);
            if (expectedType && rightNodes.length === 0) {
              rightNodes = effectiveGraph?.nodes ?? [];
            }
            const leftOpts = extractionModels[idx]?.fromOptions ?? [];
            return /* @__PURE__ */ jsxs("div", { className: "grid grid-cols-1 gap-2 rounded-lg border border-outline-variant/15 p-2 md:grid-cols-[1fr_1fr_auto]", children: [
              /* @__PURE__ */ jsxs("select", { className: inputClass, disabled: controlsLocked, ...register(`remaps.${idx}.from_node_id`), children: [
                /* @__PURE__ */ jsx2("option", { value: "", children: t("hitl.remap.leftPlaceholder") }),
                leftOpts.map((opt) => /* @__PURE__ */ jsx2("option", { value: opt.node_id, children: opt.label }, opt.node_id))
              ] }),
              /* @__PURE__ */ jsxs("select", { className: inputClass, disabled: controlsLocked, ...register(`remaps.${idx}.to_node_id`), children: [
                /* @__PURE__ */ jsx2("option", { value: "", children: t("hitl.remap.rightPlaceholder") }),
                rightNodes.map((n) => {
                  const nid = String(n.node_id ?? "").trim();
                  const cn = String(n.canonical_name ?? "").trim();
                  const lab = cn ? `${cn} (${nid})` : nid;
                  return /* @__PURE__ */ jsx2("option", { value: nid, children: lab }, nid);
                })
              ] }),
              /* @__PURE__ */ jsx2(
                "button",
                {
                  type: "button",
                  className: "btn-secondary",
                  disabled: controlsLocked || remapArray.fields.length <= 1,
                  onClick: () => {
                    remapArray.remove(idx);
                    setRemapMissingIds((prev) => prev.filter((_, i) => i !== idx));
                  },
                  children: t("hitl.delete")
                }
              )
            ] }, field.id);
          }) }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked,
              onClick: () => {
                remapArray.append({ from_node_id: "", to_node_id: "" });
                setRemapMissingIds((prev) => [...prev, ""]);
              },
              children: t("hitl.remap.addRow")
            }
          ),
          uiMode === "expert" ? /* @__PURE__ */ jsxs(Fragment, { children: [
            /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.remap.waiveAdvanced") }),
            /* @__PURE__ */ jsx2("input", { className: inputClass, disabled: controlsLocked, ...register("waiveIdsComma") })
          ] }) : null,
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked,
              onClick: () => {
                const rows = getValues("remaps").map((r) => ({
                  from_node_id: r.from_node_id.trim(),
                  to_node_id: r.to_node_id.trim()
                })).filter((r) => r.from_node_id && r.to_node_id);
                setPreview({
                  title: t("hitl.remap.previewTitle"),
                  bullets: rows.slice(0, 6).map((r) => `${r.from_node_id} \u2192 ${r.to_node_id}`).concat(rows.length > 6 ? [`\u2026 +${rows.length - 6}`] : []),
                  confirmLabel: t("hitl.remap.previewConfirm"),
                  onConfirm: () => void onExtractionRemap({
                    entity_remaps: uiMode === "expert" ? rows : rows.slice(0, Math.max(1, rows.length)),
                    waive_mandatory_node_ids: uiMode === "expert" ? waiveList() : []
                  })
                });
              },
              children: t("hitl.remap.previewApply")
            }
          )
        ] }) : null,
        selectedSolution === "b_story" && reason === HITL_REASON.B_STORY ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: t("hitl.bStory.sectionTitle") }),
          bStoryDisplay.bullets.length > 0 ? /* @__PURE__ */ jsx2("ul", { className: "mb-2 list-inside list-disc font-body text-sm text-on-surface", children: bStoryDisplay.bullets.map((b, i) => /* @__PURE__ */ jsx2("li", { children: b }, i)) }) : null,
          uiMode === "expert" ? /* @__PURE__ */ jsxs(Fragment, { children: [
            /* @__PURE__ */ jsx2("label", { className: "auteur-label", children: t("hitl.bStory.notesExpert") }),
            /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(4), disabled: controlsLocked, ...register("bAnalysis") }),
            /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.bStory.resolvedIds") }),
            /* @__PURE__ */ jsx2(
              TokenEditor,
              {
                values: watch("bResolved"),
                onAdd: (v) => setValue("bResolved", Array.from(/* @__PURE__ */ new Set([...watch("bResolved"), v]))),
                onRemove: (v) => setValue("bResolved", watch("bResolved").filter((x) => x !== v)),
                input: tokenInput,
                onInput: setTokenInput,
                disabled: controlsLocked
              }
            ),
            /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.bStory.evidenceIds") }),
            /* @__PURE__ */ jsx2(
              TokenEditor,
              {
                values: watch("bEvidence"),
                onAdd: (v) => setValue("bEvidence", Array.from(/* @__PURE__ */ new Set([...watch("bEvidence"), v]))),
                onRemove: (v) => setValue("bEvidence", watch("bEvidence").filter((x) => x !== v)),
                input: tokenInputEvidence,
                onInput: setTokenInputEvidence,
                disabled: controlsLocked
              }
            )
          ] }) : null,
          /* @__PURE__ */ jsxs("div", { className: "mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2", children: [
            /* @__PURE__ */ jsx2(
              "button",
              {
                type: "button",
                className: "rounded-xl border border-tertiary/40 bg-tertiary/15 px-4 py-4 text-left font-label text-sm font-semibold text-tertiary transition-colors hover:bg-tertiary/25 disabled:opacity-40",
                disabled: controlsLocked,
                onClick: () => onBStoryJudgement({
                  action: "force_resolve",
                  resolved_b_stories: watch("bResolved"),
                  resolution_evidence_event_ids: watch("bEvidence"),
                  resolution_analysis: watch("bAnalysis")
                }),
                children: t("hitl.bStory.yes")
              }
            ),
            /* @__PURE__ */ jsx2(
              "button",
              {
                type: "button",
                className: "rounded-xl border border-outline-variant/30 bg-surface-container-highest/50 px-4 py-4 text-left font-label text-sm font-semibold text-on-surface transition-colors hover:border-outline-variant/50 disabled:opacity-40",
                disabled: controlsLocked,
                onClick: () => setBStoryRejectOpen(true),
                children: t("hitl.bStory.no")
              }
            )
          ] }),
          bStoryRejectOpen ? /* @__PURE__ */ jsxs("div", { className: "mt-3 rounded-lg border border-outline-variant/20 bg-surface-container-low/80 p-3", children: [
            /* @__PURE__ */ jsx2("label", { className: "auteur-label", children: t("hitl.bStory.noExpandLabel") }),
            /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(3), disabled: controlsLocked, ...register("bRejectNote") }),
            /* @__PURE__ */ jsx2("label", { className: "auteur-label mt-2", children: t("hitl.bStory.rejectResume") }),
            /* @__PURE__ */ jsx2("select", { className: inputClass, disabled: controlsLocked, ...register("bRejectResume"), children: B_STORY_REJECT_RESUME_OPTIONS.map((o) => /* @__PURE__ */ jsx2("option", { value: o.value, children: t(`hitl.bStory.resumeOption.${o.value}`, o.label) }, o.value)) }),
            /* @__PURE__ */ jsxs("div", { className: "mt-2 flex flex-col gap-2 sm:flex-row", children: [
              /* @__PURE__ */ jsx2(
                "button",
                {
                  type: "button",
                  className: btnClass + " sm:flex-1",
                  disabled: controlsLocked,
                  onClick: () => void onBStoryJudgement({
                    action: "reject",
                    reject_resume_from: watch("bRejectResume"),
                    reason: (getValues("bRejectNote").trim() || getValues("bAnalysis")).slice(0, 500)
                  }),
                  children: t("hitl.bStory.rejectSubmit")
                }
              ),
              /* @__PURE__ */ jsx2(
                "button",
                {
                  type: "button",
                  className: "btn-secondary mt-2 w-full text-xs sm:mt-0 sm:flex-1",
                  disabled: controlsLocked,
                  onClick: () => {
                    setBStoryRejectOpen(false);
                    setValue("bRejectNote", "");
                  },
                  children: t("hitl.bStory.rejectCancel")
                }
              )
            ] })
          ] }) : null
        ] }) : null,
        selectedSolution === "prune" && reason === HITL_REASON.CONTEXT ? /* @__PURE__ */ jsxs(Fragment, { children: [
          /* @__PURE__ */ jsx2("h3", { className: "mb-2 font-headline text-xs font-bold text-on-surface", children: t("hitl.prune.title") }),
          /* @__PURE__ */ jsx2("p", { className: "mb-2 font-body text-xs text-on-surface-variant", children: t("hitl.prune.hint") }),
          /* @__PURE__ */ jsx2("div", { className: "flex flex-col gap-2", children: [
            { v: 0, label: t("hitl.prune.tier0") },
            { v: 1, label: t("hitl.prune.tier1") },
            { v: 2, label: t("hitl.prune.tier2") }
          ].map((row) => /* @__PURE__ */ jsxs("label", { className: "flex cursor-pointer items-center gap-2 font-body text-sm text-on-surface", children: [
            /* @__PURE__ */ jsx2(
              "input",
              {
                type: "radio",
                name: "prune-tier",
                checked: watch("pruneProductTier") === row.v,
                onChange: () => setValue("pruneProductTier", row.v),
                disabled: controlsLocked
              }
            ),
            row.label
          ] }, row.v)) }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: btnClass,
              disabled: controlsLocked,
              onClick: () => onContextPrune?.({ graph_rag_context_tier: watch("pruneProductTier"), reason: "author_context_prune" }),
              children: t("hitl.prune.apply")
            }
          )
        ] }) : null,
        hitlActive && solutionList.length === 0 ? /* @__PURE__ */ jsx2("p", { className: "font-body text-sm text-on-surface-variant", children: t("hitl.noDedicatedForm") }) : null,
        hitlActive && solutionList.length > 0 && selectedSolution == null ? /* @__PURE__ */ jsx2("p", { className: "font-body text-sm text-on-surface-variant", children: t("hitl.chooseSolutionAbove") }) : null
      ] }),
      uiMode === "expert" ? /* @__PURE__ */ jsxs("details", { className: "mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-highest/20 p-3", open: advancedOpen, onToggle: (e) => setAdvancedOpen(e.target.open), children: [
        /* @__PURE__ */ jsx2("summary", { className: "cursor-pointer font-label text-sm font-semibold text-on-surface-variant", children: t("hitl.advancedSummary") }),
        /* @__PURE__ */ jsxs("div", { className: "mt-3 space-y-3 border-t border-outline-variant/10 pt-3", children: [
          /* @__PURE__ */ jsxs("p", { className: "font-mono text-[10px] text-on-surface-variant", children: [
            t("hitl.reasonCode"),
            "\uFF1A",
            reason || "\u2014",
            " \xB7 resume\uFF1A",
            resumeHint || "\u2014"
          ] }),
          /* @__PURE__ */ jsxs("div", { children: [
            /* @__PURE__ */ jsx2("h4", { className: "font-label text-xs font-bold text-on-surface", children: t("hitl.directMutation") }),
            /* @__PURE__ */ jsx2("p", { className: "mb-1 font-body text-[10px] text-on-surface-variant", children: t("hitl.directMutationWarn") }),
            /* @__PURE__ */ jsx2("textarea", { className: inputClass, rows: taRows(6), disabled: controlsLocked, ...register("injectionJson") }),
            /* @__PURE__ */ jsxs("label", { className: "mt-2 flex cursor-pointer items-start gap-2 font-body text-xs text-on-surface", children: [
              /* @__PURE__ */ jsx2(
                "input",
                {
                  type: "checkbox",
                  className: "mt-0.5",
                  ...register("advancedInjectAck"),
                  disabled: controlsLocked
                }
              ),
              /* @__PURE__ */ jsx2("span", { children: t("hitl.directMutationAck") })
            ] }),
            /* @__PURE__ */ jsx2(
              "button",
              {
                type: "button",
                className: btnClass,
                disabled: controlsLocked || !watch("advancedInjectAck"),
                onClick: () => {
                  if (!watch("advancedInjectAck")) return;
                  let parsed;
                  try {
                    parsed = JSON.parse(getValues("injectionJson"));
                  } catch {
                    return;
                  }
                  if (!Array.isArray(parsed)) {
                    return;
                  }
                  const rows = parsed;
                  setPreview({
                    title: t("hitl.previewMutationTitle"),
                    bullets: [t("hitl.previewMutationBullets", "", { count: rows.length })],
                    confirmLabel: t("hitl.confirmWrite"),
                    onConfirm: () => void onStateInjection({
                      mutations: rows
                    })
                  });
                },
                children: t("hitl.writeAndContinue")
              }
            )
          ] })
        ] })
      ] }) : null,
      preview ? /* @__PURE__ */ jsxs("div", { className: "mt-4 rounded-xl border border-secondary/30 bg-secondary/10 p-3", role: "dialog", "aria-live": "polite", children: [
        /* @__PURE__ */ jsx2("p", { className: "font-headline text-sm font-bold text-on-surface", children: preview.title }),
        /* @__PURE__ */ jsx2("ul", { className: "mt-2 list-disc list-inside font-body text-sm text-on-surface", children: preview.bullets.map((line, idx) => /* @__PURE__ */ jsx2("li", { children: line }, idx)) }),
        /* @__PURE__ */ jsxs("div", { className: "mt-3 flex gap-2", children: [
          /* @__PURE__ */ jsx2("button", { type: "button", className: "btn-secondary", onClick: () => setPreview(null), children: t("hitl.backEdit") }),
          /* @__PURE__ */ jsx2(
            "button",
            {
              type: "button",
              className: "btn-primary-gradient",
              onClick: () => {
                preview.onConfirm();
                setPreview(null);
              },
              children: preview.confirmLabel
            }
          )
        ] })
      ] }) : null
    ] }) : null
  ] });
}
function TokenEditor({
  values,
  onAdd,
  onRemove,
  input,
  onInput,
  disabled
}) {
  return /* @__PURE__ */ jsxs("div", { className: "rounded-lg border border-outline-variant/20 bg-surface-container-low p-2", children: [
    /* @__PURE__ */ jsx2("div", { className: "mb-2 flex flex-wrap gap-2", children: values.map((v) => /* @__PURE__ */ jsxs("span", { className: "inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary", children: [
      v,
      /* @__PURE__ */ jsx2(
        "button",
        {
          type: "button",
          className: "text-primary/70",
          onClick: () => onRemove(v),
          disabled,
          "aria-label": `Remove ${v}`,
          children: "\xD7"
        }
      )
    ] }, v)) }),
    /* @__PURE__ */ jsx2("div", { className: "flex gap-2", children: /* @__PURE__ */ jsx2(
      "input",
      {
        className: "auteur-input text-sm",
        value: input,
        disabled,
        onChange: (e) => onInput(e.target.value),
        onKeyDown: (e) => {
          if (e.key !== "Enter") return;
          e.preventDefault();
          const next = input.trim();
          if (!next) return;
          onAdd(next);
          onInput("");
        },
        placeholder: "Type and press Enter to add"
      }
    ) })
  ] });
}
export {
  HITL_REASON,
  HitlPanel
};
