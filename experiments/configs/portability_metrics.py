"""이식성 측정 (티켓 #32, 사전 고정). 정의: experiments/plans/PORTABILITY-METRICS.md

두 커밋(동결 커밋 → 새 환경 이식 완료 커밋) 사이에서 다음을 계산한다.

    uv run python experiments/configs/portability_metrics.py <base> <after> --env assembly

- core_diff_lines      : src/asel/core/ 의 추가+삭제 줄 수
- engine_diff_lines    : 코어 밖 공용 엔진(src/asel/ 중 core·domains 제외)의 추가+삭제 줄 수
- adapter_lines        : src/asel/domains/ 의 추가+삭제 줄 수 (도메인 전용 코드)
- config_lines         : scenarios/ 의 추가 줄 수 (설정)
- public_interface_changes : 코어 공개 이름(모듈 최상위 이름, 데이터 클래스 필드, 행동·사건 이름)의 추가+삭제 수
- new_concepts         : 공통 언어 목록(asel.vocabulary)의 개념·값·행동·사건 추가+삭제 수
- config_only_ratio    : config_lines / (config_lines + adapter_lines + engine_diff_lines + core_diff_lines)
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def numstat(base: str, after: str, path: str, exclude: tuple[str, ...] = (), added_only: bool = False) -> int:
    total = 0
    for line in git("diff", "--numstat", base, after, "--", path).splitlines():
        a, d, p = line.split("\t", 2)
        if any(p.startswith(x) for x in exclude) or a == "-":
            continue
        total += int(a) + (0 if added_only else int(d))
    return total


def _core_files(commit: str) -> list[str]:
    return [p for p in git("ls-tree", "-r", "--name-only", commit, "src/asel/core").splitlines() if p.endswith(".py")]


def public_names(commit: str) -> set[str]:
    names: set[str] = set()
    for path in _core_files(commit):
        tree = ast.parse(git("show", f"{commit}:{path}"))
        mod = path.rsplit("/", 1)[-1][:-3]
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                names.add(f"{mod}.{node.name}")
                if isinstance(node, ast.ClassDef):
                    for b in node.body:
                        if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                            names.add(f"{mod}.{node.name}.{b.target.id}")
                        elif isinstance(b, ast.Assign):
                            for t in b.targets:
                                if isinstance(t, ast.Name) and t.id.isupper():
                                    val = b.value.value if isinstance(b.value, ast.Constant) else t.id
                                    names.add(f"{mod}.{node.name}.{t.id}={val}")
                        elif isinstance(b, ast.FunctionDef) and not b.name.startswith("_"):
                            names.add(f"{mod}.{node.name}.{b.name}()")
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        names.add(f"{mod}.{t.id}")
    return names


def vocabulary_items(commit: str) -> set[str]:
    try:
        src = git("show", f"{commit}:src/asel/vocabulary.py")
    except subprocess.CalledProcessError:
        return set()
    tree = ast.parse(src)
    items: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(target, "id", "")
            if name in ("CONCEPTS", "VALUE_CONCEPTS", "ACTIONS", "EVENTS") and isinstance(node.value, ast.Dict):
                for k in node.value.keys:
                    items.add(f"{name}:{ast.unparse(k)}")
    return items


def measure(base: str, after: str) -> dict:
    core = numstat(base, after, "src/asel/core")
    engine = numstat(base, after, "src/asel", exclude=("src/asel/core/", "src/asel/domains/"))
    adapter = numstat(base, after, "src/asel/domains")
    config = numstat(base, after, "scenarios", added_only=True)
    pub_b, pub_a = public_names(base), public_names(after)
    voc_b, voc_a = vocabulary_items(base), vocabulary_items(after)
    denom = config + adapter + engine + core
    return {
        "base": git("rev-parse", "--short", base).strip(),
        "after": git("rev-parse", "--short", after).strip(),
        "core_diff_lines": core,
        "engine_diff_lines": engine,
        "adapter_lines": adapter,
        "config_lines": config,
        "public_interface_changes": len(pub_a ^ pub_b),
        "public_interface_added": sorted(pub_a - pub_b),
        "public_interface_removed": sorted(pub_b - pub_a),
        "new_concepts": len(voc_a ^ voc_b),
        "concepts_added": sorted(voc_a - voc_b),
        "concepts_removed": sorted(voc_b - voc_a),
        "config_only_ratio": round(config / denom, 4) if denom else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("after")
    ap.add_argument("--env", required=True)
    a = ap.parse_args()
    print(json.dumps({"env": a.env, **measure(a.base, a.after)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
