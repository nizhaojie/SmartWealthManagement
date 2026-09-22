// 打字机限速器：把「一瞬间到齐」的增量文本按最小间隔逐字转发给下游，
// 让逐字渲染有可感知的节奏。
//
// 它是「最小间隔限速」，不是「固定延迟」：
// - 数据到得快（当前假流式：答案完整生成后才逐字推，几毫秒全到）→ 压到间隔上匀速吐；
// - 数据到得慢（未来真流式：模型边生成边推，本身就有间隔）→ 有字立即转、无字空转即停。
//
// 「定案」也在这里排队：end() 注册的回调要等缓冲吐空才执行。这样 done 帧到达
// 不会把还没吐完的字一次性冲掉——否则「改了间隔却看不出效果」。

export type Typewriter = {
  /** 追加一段增量文本，按最小间隔逐字转发给 onChar。 */
  push(text: string): void;
  /** 注册「缓冲吐空后执行」的回调；若缓冲已空则立即执行。 */
  end(onFinished: () => void): void;
  /** 立即吐完剩余缓冲（断流收尾用），并执行尚未执行的 end 回调。 */
  flush(): void;
};

export function createTypewriter(
  intervalMs: number,
  onChar: (char: string) => void,
): Typewriter {
  let buffer: string[] = [];
  let pendingEnd: (() => void) | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function runPendingEnd(): void {
    const cb = pendingEnd;
    pendingEnd = null;
    if (cb) {
      cb();
    }
  }

  function tick(): void {
    const char = buffer.shift();
    if (char === undefined) {
      stop();
      runPendingEnd();
      return;
    }
    onChar(char);
    // 吐完最后一个字的那一刻缓冲已空，就该定案，不必多等一个间隔的空转 tick。
    if (buffer.length === 0) {
      stop();
      runPendingEnd();
    }
  }

  return {
    push(text) {
      // Array.from 按 code point 拆，中文逐字、代理对（生僻字/emoji）不拆散。
      buffer.push(...Array.from(text));
      if (timer === null) {
        timer = setInterval(tick, intervalMs);
      }
    },
    end(onFinished) {
      pendingEnd = onFinished;
      if (buffer.length === 0) {
        stop();
        runPendingEnd();
      }
    },
    flush() {
      stop();
      if (buffer.length > 0) {
        const rest = buffer.join("");
        buffer = [];
        onChar(rest);
      }
      runPendingEnd();
    },
  };
}
