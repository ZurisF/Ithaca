const routeCatalog = {
  walkthrough: {
    label: "项目导览",
    short: "导览",
    question: "从用户选定仓库开始，到项目快照可以用于面试，完整链路是什么？",
    answers: [
      {
        text: "先清点授权文件，脱敏后解析；再形成项目链路和证据，用户确认后固化快照。",
        read: "回答覆盖了输入、处理顺序、画像产物与用户确认，主流程已经可以复述。",
        move: "完成本链 → 转场",
        rules: "导览目标已覆盖；允许进入下一条已选择路线。",
        why: "主流程已经说清，继续复述不会增加理解；下一问应转向设计依据。",
        gaps: 0,
        outcome: "next"
      },
      {
        text: "就是把整个仓库交给模型，然后生成一个总结。",
        read: "回答只给出了模糊结果，缺少授权、脱敏、证据和确认环节。",
        move: "留在本链 → 澄清",
        rules: "当前训练单元未覆盖；禁止无理由切换到新主题。",
        why: "先补齐端到端链路，后面的设计取舍才有共同前提。",
        gaps: 4,
        outcome: "clarify"
      },
      {
        text: "核心是增量更新；文件改动后只重算受影响的部分。",
        read: "用户没有完整回答导览问题，但主动暴露了一个高价值风险：增量索引失效。",
        move: "临时开分支",
        rules: "增量更新与当前链存在直接依赖；保存导览恢复点后允许进入故障分支。",
        why: "先追问用户主动提出的关键风险，问清后再回到未完成的项目导览。",
        gaps: 2,
        outcome: "branch"
      }
    ]
  },
  tradeoff: {
    label: "设计取舍",
    short: "取舍",
    question: "为什么不把整个仓库直接塞进一个超长 Prompt，而要先形成结构化快照？",
    answers: [
      {
        text: "上下文和成本只是表层原因，更重要的是要有明确范围、证据引用和可增量复用的事实层。",
        read: "回答区分了资源限制与产品目标，也给出了结构化快照的核心收益。",
        move: "深入 → 改变约束",
        rules: "选择和动机已覆盖；下一合法深度是替代方案或约束变化。",
        why: "通过改变仓库规模和更新频率，检验这套取舍是否仍然成立。",
        gaps: 1,
        outcome: "deepen"
      },
      {
        text: "因为模型上下文放不下。",
        read: "回答命中了一个原因，但尚未说明证据、复用和一致性价值。",
        move: "留在本链 → 深挖动机",
        rules: "当前回答可继续追问；无需换链。",
        why: "同一个选择可能有多层原因，先确认是否只是在做上下文压缩。",
        gaps: 3,
        outcome: "clarify"
      },
      {
        text: "先别聊架构，我想看看文件变更时快照会不会过期。",
        read: "识别到明确的用户切换请求，目标是增量更新与失效处理。",
        move: "用户切换 → 故障链",
        rules: "用户拥有节奏控制权；保存当前取舍链位置，再进入故障恢复。",
        why: "这是用户明确指定的关联方向，切换不会被当作答非所问。",
        gaps: 1,
        outcome: "branch"
      }
    ]
  },
  failure: {
    label: "故障恢复",
    short: "故障",
    question: "如果文件改名但内容没变，系统怎样避免旧证据残留或整仓重算？",
    answers: [
      {
        text: "同时用内容哈希和路径标识：内容可复用，但旧路径引用必须失效并重新绑定证据位置。",
        read: "回答同时处理了计算复用和引用正确性，覆盖了主要故障路径。",
        move: "完成分支 → 返回",
        rules: "分支目标已覆盖；若分支栈非空，必须优先回到原链。",
        why: "风险已经问清，现在返回先前未完成的主线，避免越聊越散。",
        gaps: 0,
        outcome: "return"
      },
      {
        text: "有哈希就行，内容没变应该不需要处理。",
        read: "回答考虑了计算缓存，但忽略了路径、行号和引用仍可能失效。",
        move: "留在分支 → 反例",
        rules: "关键故障尚未覆盖；允许给出约束，不允许直接判定回答错误并切走。",
        why: "用引用失效这个反例继续追问，比直接告诉答案更符合模拟面试。",
        gaps: 2,
        outcome: "clarify"
      },
      {
        text: "这部分我不知道，先记录下来，继续下一块。",
        read: "识别为未知加主动切换，不把未知误判为完成。",
        move: "记录缺口 → 转场",
        rules: "保存 unresolved gap；允许用户结束当前分支。",
        why: "用户已经明确停止深挖；缺口进入复盘与下次训练，不在本轮纠缠。",
        gaps: 1,
        outcome: "next"
      }
    ]
  },
  evaluation: {
    label: "质量评估",
    short: "评估",
    question: "你怎样证明这份项目快照真的足以支撑高质量模拟面试？",
    answers: [
      {
        text: "用黄金项目包评估事实准确率、引用有效性和未知项价值，再观察问题相关性、重复率与信息增益。",
        read: "回答同时覆盖画像质量和面试效果，已经形成可执行的评估闭环。",
        move: "深入 → Bad Case",
        rules: "指标已覆盖；允许进入评测数据与失败案例。",
        why: "指标说清后，下一步应验证评测集如何发现真实退化。",
        gaps: 1,
        outcome: "deepen"
      },
      {
        text: "让用户体验一下，觉得问题不错就可以。",
        read: "回答只有主观体验，没有离线基线、证据准确性或回归标准。",
        move: "留在本链 → 拆指标",
        rules: "评估目标未覆盖；提供具体观察维度但不泄露参考答案。",
        why: "把“不错”拆成可以比较的结果，才能判断版本是否真的进步。",
        gaps: 4,
        outcome: "clarify"
      },
      {
        text: "评估先放一放，我更想练自己到底负责了什么。",
        read: "用户明确请求进入个人贡献链。",
        move: "用户切换 → 贡献链",
        rules: "尊重主动切换；保存评估链恢复点。",
        why: "训练目标由用户控制，系统保留未完成位置供之后恢复。",
        gaps: 2,
        outcome: "next"
      }
    ]
  },
  ownership: {
    label: "个人贡献",
    short: "贡献",
    question: "这套项目观察与快照机制中，哪些决策是你亲自做的，哪些来自团队共识？",
    answers: [
      {
        text: "我负责快照结构和增量更新方案；安全规则由同事主导，我参与了评审和边界定义。",
        read: "回答区分了独立负责、协作和评审贡献，没有把团队成果全部归于个人。",
        move: "深入 → 决策证据",
        rules: "职责边界已覆盖；允许追问一次具体决策及结果。",
        why: "从职责声明进入可验证的行动和结果，能检验贡献是否具体。",
        gaps: 1,
        outcome: "deepen"
      },
      {
        text: "基本都是我做的。",
        read: "回答范围过大，缺少任务边界、协作对象和可验证行动。",
        move: "留在本链 → 具体化",
        rules: "贡献只能来自用户陈述或提交证据；需要缩小到一个具体决策。",
        why: "选择一个模块追问需求、行动与结果，比质疑用户更有效。",
        gaps: 3,
        outcome: "clarify"
      },
      {
        text: "我想先暂停，之后从贡献这里继续。",
        read: "识别为暂停请求，并指定恢复位置。",
        move: "暂停并保存",
        rules: "持久化当前链、开放缺口与分支栈；本轮不再生成问题。",
        why: "用户控制节奏。恢复时从语义断点继续，而不是重新开始。",
        gaps: 1,
        outcome: "pause"
      }
    ]
  },
  evolution: {
    label: "演进复盘",
    short: "复盘",
    question: "如果再做一版，你会优先修改这套机制的哪一处？为什么不是其他地方？",
    answers: [
      {
        text: "先完善跨会话训练地图，因为它直接决定广度和重练价值；精细调用图可以后置。",
        read: "回答给出了优先级、影响范围和明确的暂缓项。",
        move: "完成本链",
        rules: "复盘目标已覆盖；可以进入下一条路线或由用户结束。",
        why: "这一链已经形成完整判断，继续追问只在用户希望更深时发生。",
        gaps: 0,
        outcome: "next"
      },
      {
        text: "全部都要优化。",
        read: "回答没有优先级、资源约束和选择依据。",
        move: "留在本链 → 施加约束",
        rules: "允许增加时间或人力限制，促使用户做出选择。",
        why: "复盘的价值在于判断优先级，而不是罗列愿望。",
        gaps: 3,
        outcome: "clarify"
      },
      {
        text: "先到这里，结束面试。",
        read: "识别为用户主动结束。",
        move: "保存并结束",
        rules: "用户可随时结束；保存已完成路线和未决缺口。",
        why: "停止权属于用户，不要求走完预设链路。",
        gaps: 0,
        outcome: "finish"
      }
    ]
  }
};

const clarificationQuestions = {
  walkthrough: "先只讲主流程：系统在读取源码之前、读取之后，以及用户确认之后，各自产生什么？",
  tradeoff: "除了上下文放不下，如果仓库很小，你仍然需要结构化快照吗？为什么？",
  failure: "文件内容没变，但路径和行号都变了；原来的证据引用还能直接使用吗？",
  evaluation: "把“问题不错”拆开看，你会分别怎样衡量事实可靠性和追问质量？",
  ownership: "只选一个你亲自推动的决策：当时的问题、你的动作和最终结果分别是什么？",
  evolution: "假设只有两周和一名工程师，你会先做哪一件事？"
};

const scopeLabels = {
  single: "项目材料 → 上下文快照",
  multi: "导入、面试编排、赛后复盘",
  all: "全项目关键链路（系统动态选择）"
};

const state = {
  selectedRoutes: ["walkthrough", "tradeoff", "failure"],
  routeIndex: 0,
  activeRoute: null,
  turn: 0,
  branchStack: [],
  done: new Set(),
  running: false,
  paused: false,
  gaps: 0
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function setActiveScope(button) {
  $$("#scope-options .segment").forEach((item) => item.classList.toggle("active", item === button));
  $("#scope-label").textContent = scopeLabels[button.dataset.scope];
}

function toggleRoute(button) {
  const route = button.dataset.route;
  button.classList.toggle("active");
  const active = $$(".route-chip.active").map((item) => item.dataset.route);
  if (!active.length) {
    button.classList.add("active");
    return;
  }
  state.selectedRoutes = active;
}

function renderRail() {
  const rail = $("#route-rail");
  rail.innerHTML = "";
  state.selectedRoutes.forEach((routeId, index) => {
    if (index) {
      const link = document.createElement("div");
      link.className = "rail-link";
      rail.appendChild(link);
    }
    const route = routeCatalog[routeId];
    const node = document.createElement("div");
    const isBranch = state.branchStack.length && routeId === "failure" && state.activeRoute === "failure";
    node.className = `rail-node${state.done.has(routeId) ? " done" : ""}${state.activeRoute === routeId ? " active" : ""}${isBranch ? " branch" : ""}`;
    node.innerHTML = `<small>${isBranch ? "BRANCH" : `CHAIN ${String(index + 1).padStart(2, "0")}`}</small><b>${route.label}</b>`;
    rail.appendChild(node);
  });
}

function renderQuestion(questionOverride) {
  const route = routeCatalog[state.activeRoute];
  $("#question-text").textContent = questionOverride || route.question;
  $("#turn-counter").textContent = `TURN ${String(state.turn).padStart(2, "0")}`;
  $("#state-chain").textContent = route.label;
  $("#state-move").textContent = "等待回答";
  $("#state-stack").textContent = String(state.branchStack.length);
  $("#state-gaps").textContent = String(state.gaps);

  const answers = $("#answer-options");
  answers.innerHTML = "";
  route.answers.forEach((answer) => {
    const button = document.createElement("button");
    button.textContent = answer.text;
    button.addEventListener("click", () => handleAnswer(answer));
    answers.appendChild(button);
  });
  renderRail();
}

function startDemo() {
  state.selectedRoutes = $$(".route-chip.active").map((item) => item.dataset.route);
  state.routeIndex = 0;
  state.activeRoute = state.selectedRoutes[0];
  state.turn = 1;
  state.branchStack = [];
  state.done = new Set();
  state.running = true;
  state.paused = false;
  state.gaps = 0;
  $("#pause-button").textContent = "暂停";
  $("#model-readout").textContent = "路线已经生成。等待用户回答后，模型会输出结构化语义观察。";
  $("#rules-readout").textContent = `本场允许 ${state.selectedRoutes.length} 条训练链；一次只问一个主要问题。`;
  $("#why-next").textContent = "第一问先建立共同的项目事实，再根据回答决定深挖、分支或转场。";
  renderQuestion();
  $("#engine").scrollIntoView({ behavior: "smooth", block: "start" });
}

function nextSelectedRoute() {
  const currentIndex = state.selectedRoutes.indexOf(state.activeRoute);
  for (let offset = 1; offset <= state.selectedRoutes.length; offset += 1) {
    const candidateIndex = (currentIndex + offset) % state.selectedRoutes.length;
    const candidate = state.selectedRoutes[candidateIndex];
    if (!state.done.has(candidate)) return candidate;
  }
  return null;
}

function ensureFailureRoute() {
  if (!state.selectedRoutes.includes("failure")) {
    state.selectedRoutes.splice(Math.min(state.routeIndex + 1, state.selectedRoutes.length), 0, "failure");
  }
}

function disableAnswers() {
  $$("#answer-options button").forEach((button) => { button.disabled = true; });
}

function handleAnswer(answer) {
  if (!state.running || state.paused) return;
  disableAnswers();
  state.turn += 1;
  state.gaps = answer.gaps;
  $("#model-readout").textContent = answer.read;
  $("#rules-readout").textContent = answer.rules;
  $("#state-move").textContent = answer.move;
  $("#state-gaps").textContent = String(state.gaps);
  $("#why-next").textContent = answer.why;

  window.setTimeout(() => {
    if (answer.outcome === "clarify" || answer.outcome === "deepen") {
      renderQuestion(clarificationQuestions[state.activeRoute]);
      return;
    }

    if (answer.outcome === "branch") {
      ensureFailureRoute();
      if (state.activeRoute !== "failure") {
        state.branchStack.push(state.activeRoute);
        state.activeRoute = "failure";
      }
      renderQuestion();
      return;
    }

    if (answer.outcome === "return" && state.branchStack.length) {
      state.done.add(state.activeRoute);
      state.activeRoute = state.branchStack.pop();
      $("#state-stack").textContent = String(state.branchStack.length);
      renderQuestion(clarificationQuestions[state.activeRoute]);
      return;
    }

    if (answer.outcome === "pause") {
      state.paused = true;
      $("#pause-button").textContent = "继续";
      $("#question-text").textContent = "会话已暂停。当前链、开放缺口和返回位置都已保存。";
      $("#answer-options").innerHTML = "<button disabled>点击右上角“继续”恢复</button>";
      renderRail();
      return;
    }

    if (answer.outcome === "finish") {
      finishDemo();
      return;
    }

    state.done.add(state.activeRoute);
    const next = nextSelectedRoute();
    if (!next) {
      finishDemo();
      return;
    }
    state.activeRoute = next;
    renderQuestion();
  }, 420);
}

function finishDemo() {
  state.running = false;
  state.done.add(state.activeRoute);
  renderRail();
  $("#question-text").textContent = "这场演示已保存：完成的链路、未决缺口和下一次建议入口都会进入训练历史。";
  $("#answer-options").innerHTML = "<button id='again-button'>重新跑一遍，尝试另一种回答</button>";
  $("#again-button").addEventListener("click", startDemo);
  $("#state-move").textContent = "用户结束 / 自然收束";
  $("#why-next").textContent = "没有强制走完所有路线。结束权属于用户，未完成部分留给下一场。";
}

function togglePause() {
  if (!state.running) return;
  state.paused = !state.paused;
  $("#pause-button").textContent = state.paused ? "继续" : "暂停";
  if (state.paused) {
    disableAnswers();
    $("#state-move").textContent = "暂停并保存";
    $("#rules-readout").textContent = "程序保存当前链、分支栈、覆盖和缺口；暂停不计入面试轮次。";
    $("#why-next").textContent = "恢复后从当前问题继续，不重新规划整场。";
  } else {
    renderQuestion();
    $("#rules-readout").textContent = "状态恢复完成；当前路线和问题保持不变。";
  }
}

$$("#scope-options .segment").forEach((button) => button.addEventListener("click", () => setActiveScope(button)));
$$(".route-chip").forEach((button) => button.addEventListener("click", () => toggleRoute(button)));
$("#start-demo").addEventListener("click", startDemo);
$("#pause-button").addEventListener("click", togglePause);
$("#reset-button").addEventListener("click", startDemo);

renderRail();
