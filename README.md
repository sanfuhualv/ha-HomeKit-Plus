# HomeKit Plus

Home Assistant 的 HomeKit Bridge 分支版本。官方桥接只能按类别批量同步，这个版本可以直接勾选具体的灯、开关、空调等实体，只把你选中的同步到 Apple「家庭」。

适用于 Home Assistant Core 2026.10.x；集成域 `homekit_plus`，可与内置的 HomeKit 集成并存。

## 安装

1. 把 `custom_components/homekit_plus` 整个复制到 Home Assistant 的配置目录下
2. 完整重启 Home Assistant
3. 浏览器按 Ctrl+F5 刷新

## 添加桥接

1. **设置 → 设备与服务 → 添加集成**，搜索 **HomeKit Plus**
2. 搜索并勾选要同步的实体，提交
3. 下一页显示配对信息，用 Apple「家庭」App 扫码完成配对

## 修改已同步的实体

进入 **设置 → 设备与服务 → HomeKit Plus**，点桥接旁的**配置**按钮，或从 **⋮ → 重新配置** 进入：

- 已选实体显示在选择框里，点 **×** 可以移除；搜索并勾选即可添加
- 点**提交**保存，桥接按新的清单重新加载，不会新建第二个桥接

这只会改变同步哪些实体，不会删除 Home Assistant 中的设备或实体。由 `configuration.yaml` 创建的桥接仍需在那里修改 `filter`；摄像头和空调的额外设置走原有的「配置」流程。

## 打包

```
python scripts/package.py            # 安装包
python scripts/package.py --source   # GitHub 源码包
```

## 许可

基于 [Home Assistant Core 的 HomeKit Bridge](https://github.com/home-assistant/core/tree/2026.10.1/homeassistant/components/homekit)，Apache-2.0，见 `LICENSE.md` 与 `NOTICE`。图标来自 [Home Assistant brands](https://github.com/home-assistant/brands)。
