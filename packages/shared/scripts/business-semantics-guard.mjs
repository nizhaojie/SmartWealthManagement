// ADR-0003: packages/shared 与两个前端应用同处一个 bundle 边界之外，但仍会被
// 各自应用打包进最终产物。一旦业务语义混进这里，客户端的 JS 产物里就会带着
// 内部专属的概念（风控规则、预警分级、审核流状态、画像权重……），扒开
// sourcemap 就能读到——这正是 ADR-0003 里"两个应用分开"想要避免的事。
//
// 判据：
//   算业务语义 —— 只服务于某个业务领域、离开这个领域就没有意义的概念标识，
//     例如风控规则字段、预警分级、审核流状态、画像权重，以及候选池、工单、
//     适当性匹配、投顾内容这类同级别的领域词汇（详见 CONTEXT.md 的 Language
//     一节）。
//   不算业务语义 —— 不依赖任何业务领域就能理解、纯粹服务于"两个应用都要用
//     一份"这件事本身的技术性代码：HTTP 客户端、响应拆包、错误码映射、日期
//     与金额格式化、主题令牌、图表壳。
//
// 检查方式是对 packages/shared/src 下的源码逐行做词法匹配，而不是解析 AST：
// 业务语义一旦以任何形式（标识符、注释、字符串字面量）出现在这里，就会以
// 某种形式进最终产物，值得同等对待。英文词条按 camelCase / snake_case /
// kebab-case 的词边界切分成 token 序列做整词匹配，避免像 "networkOrderId"
// 这种纯字符巧合被误判为词条 "workOrder"；中文词条没有这类切分依据，按原样
// 做子串匹配。

export const BUSINESS_SEMANTIC_TERMS = [
  // 风控规则字段
  { category: "风控规则字段", term: "riskRule" },
  { category: "风控规则字段", term: "风控规则" },
  { category: "风控规则字段", term: "ruleField" },
  { category: "风控规则字段", term: "规则字段" },
  { category: "风控规则字段", term: "ruleOperator" },
  { category: "风控规则字段", term: "ruleThreshold" },

  // 预警分级
  { category: "预警分级", term: "alertLevel" },
  { category: "预警分级", term: "alertGrade" },
  { category: "预警分级", term: "预警分级" },
  { category: "预警分级", term: "预警等级" },
  { category: "预警分级", term: "warningLevel" },

  // 审核流状态
  { category: "审核流状态", term: "reviewStatus" },
  { category: "审核流状态", term: "reviewFlow" },
  { category: "审核流状态", term: "审核状态" },
  { category: "审核流状态", term: "审核流" },
  { category: "审核流状态", term: "aiDraft" },
  { category: "审核流状态", term: "AI原稿" },
  { category: "审核流状态", term: "advisorFinal" },
  { category: "审核流状态", term: "顾问定稿" },

  // 画像权重
  { category: "画像权重", term: "profileWeight" },
  { category: "画像权重", term: "画像权重" },
  { category: "画像权重", term: "customerProfile" },
  { category: "画像权重", term: "客户画像" },
  { category: "画像权重", term: "riskTolerance" },
  { category: "画像权重", term: "风险承受等级" },
  { category: "画像权重", term: "targetAllocation" },
  { category: "画像权重", term: "目标配置" },
  { category: "画像权重", term: "actualAllocation" },
  { category: "画像权重", term: "实际配置" },

  // 同级别的其它业务概念
  { category: "其他业务概念", term: "suitability" },
  { category: "其他业务概念", term: "适当性匹配" },
  { category: "其他业务概念", term: "candidatePool" },
  { category: "其他业务概念", term: "候选池" },
  { category: "其他业务概念", term: "workOrder" },
  { category: "其他业务概念", term: "工单" },
  { category: "其他业务概念", term: "advisoryContent" },
  { category: "其他业务概念", term: "投顾内容" },
  { category: "其他业务概念", term: "productRiskLevel" },
  { category: "其他业务概念", term: "产品风险等级" },
];

const CJK_PATTERN = /[一-鿿]/;

// 英文词条按 camelCase / snake_case / kebab-case 的词边界切分成 token 序列，
// 再要求这个序列整体、按序出现在源码某一行的 token 序列里。这样
// "networkOrderId"（token: network, order, id）不会被词条 "workOrder"
// （token: work, order）误命中——两者只是字符上碰巧相邻，并非同一个词。
// 中文词条没有大小写或分隔符可切分，按原样做子串匹配。
function tokenize(text) {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean)
    .map((token) => token.toLowerCase());
}

function containsSubsequence(haystack, needle) {
  for (let start = 0; start + needle.length <= haystack.length; start += 1) {
    let matched = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[start + offset] !== needle[offset]) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return true;
    }
  }
  return false;
}

const MATCHERS = BUSINESS_SEMANTIC_TERMS.map((entry) => {
  if (CJK_PATTERN.test(entry.term)) {
    return { ...entry, kind: "cjk" };
  }
  return { ...entry, kind: "ascii", tokens: tokenize(entry.term) };
});

export function scanTextForViolations(text, fileLabel) {
  const violations = [];
  const lines = text.split("\n");
  lines.forEach((line, index) => {
    const lineTokens = tokenize(line);
    for (const matcher of MATCHERS) {
      const hit =
        matcher.kind === "cjk"
          ? line.includes(matcher.term)
          : containsSubsequence(lineTokens, matcher.tokens);
      if (hit) {
        violations.push({ file: fileLabel, line: index + 1, term: matcher.term, category: matcher.category });
      }
    }
  });
  return violations;
}

export function formatViolation(violation) {
  return `  ${violation.file}:${violation.line}  [${violation.category}]  疑似业务语义标识: "${violation.term}"`;
}
