# 路由迁移包（260911 夜由 integration 预备，待宿主执行或授权提权）

## 目的
t260910-14（已落账）把模型路由真源改为「项目声明指向的文件」。本包完成**存量项目迁移**：
把表拷到机器级 + 在项目注册表落声明。仓内 `server/model-routes.yaml` **保留不删**（零断供兜底）。

## 目标形态
- 表：`~/.sandbar/projects/<key>/model-routes.yaml`
- 声明：`~/.sandbar/projects/<key>/project.yaml` 追加
  ```
  paths:
    model_routes: ~/.sandbar/projects/<key>/model-routes.yaml
  ```

## 执行（每个项目一遍；先 sandbar 后 dengzhufpv）
```sh
KEY=sandbar
cp ~/.sandbar/projects/$KEY/project.yaml /tmp/project-$KEY.yaml.bak      # 备份
cp <repo>/server/model-routes.yaml ~/.sandbar/projects/$KEY/model-routes.yaml
printf '\npaths:\n  model_routes: ~/.sandbar/projects/%s/model-routes.yaml\n' "$KEY" >> ~/.sandbar/projects/$KEY/project.yaml
```
## 立即验证（必须全绿才保留改动）
```sh
cd <repo> && server/engine/.venv/bin/python -c "
import sys; sys.path.insert(0,'server/engine'); import shared, json
print(shared.lookup_project('$KEY')['key'])
info=shared.resolve_routes_table('$KEY'); print(info.get('state'), info.get('declared'), info.get('path'))
"
# 期望：state=ok（或 declared 非空且 path 指向机器级），且表内容与仓内一致
```
## 真 spawn 冒烟（风险令 checklist⑤）
开一张即弃票（dev-lane），agent 起第一段后：
```sh
cat <repo>/.lane/<票号>/.sandbar/model_patch_*_gen0.yml   # 断言 provider/model == 机器级表里的 roles.<角色> 值
```
断言一致后撤票。若不一致 → 立即回滚。

## 回滚（一条命令）
```sh
cp /tmp/project-$KEY.yaml.bak ~/.sandbar/projects/$KEY/project.yaml   # 移除声明
# 可选：rm ~/.sandbar/projects/$KEY/model-routes.yaml
```
回滚后 `resolve_routes_table` 应回到 decl_missing + 兜底仓内表（分层设计保证不断供）。

## 为什么没在夜里自动执行
integration 会话的沙箱不允许写工作目录之外（`~/.sandbar/` 被拒）；无人监督时改机器级注册表 =
宿主风险令所警告的形态，故留待宿主执行或显式授权提权。
