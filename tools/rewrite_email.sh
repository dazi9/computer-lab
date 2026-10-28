#!/usr/bin/env bash
# 把历史里的 dazi9@lab 邮箱统一改写为 1804595459@qq.com
# (git 内置 filter-branch,零安装;重写后所有提交哈希变化,需 --force 推送)
set -e
cd "$(dirname "$0")/.."
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch --env-filter '
if [ "$GIT_AUTHOR_EMAIL" = "dazi9@lab" ]; then
    export GIT_AUTHOR_EMAIL=1804595459@qq.com
fi
if [ "$GIT_COMMITTER_EMAIL" = "dazi9@lab" ]; then
    export GIT_COMMITTER_EMAIL=1804595459@qq.com
fi
' -- --all
echo "== 改写后剩余的旧邮箱(应为空) =="
git log --format='%ae %ce' --all | sort -u | grep dazi9@lab || echo "(无)"
