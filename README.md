# NeAI Shared Desktop

Windows 上で **人間と NeAI が同じ画面を共有**し、NeAI が実マウスカーソルで PC を操作するためのローカル基盤です。

これは座標だけを渡す単純なロボットではありません。NeAI は共有デスクトップの PNG を取得し、その画面を見ながら次の操作を決めます。人間も同じ画面を見て、同じマウスカーソルを共有します。

## 設計思想

```text
共有画面 (GET /api/screen)
    ↓
NeAI が画面を理解
    ↓
実マウスカーソルで操作 (POST /api/actions or /api/plans)
    ↓
画面が変わる → 再取得 → 次の操作
```

- 操作経路は **実マウスカーソルだけ** です。キー入力・シェル・ウィンドウ API は使いません。
- 座標は「外部から与えられた数字」ではなく、**共有画面のピクセル空間** です。
- 人間と NeAI は同じデスクトップを見ます。NeAI が動かすのも Windows の実カーソルです。

## 起動

Windows と Python 3.11+ があれば、追加パッケージなしで動きます。

```powershell
python neai_server.py
```

ブラウザで `http://127.0.0.1:8765` を開きます。画面プレビューが共有デスクトップです。

## 入力システム

1. **依頼入力** — 人間が自然文で NeAI に依頼 (`POST /api/intents`)
2. **操作入力** — NeAI が共有画面を見たうえで送るカーソル操作
   - 1 手ずつ: `POST /api/actions`
   - 複数手: `POST /api/plans`

いずれも **ARM 後のみ** 実行されます。

## NeAI 接続プロトコル

```text
Human -> POST /api/intents
NeAI  -> GET  /api/intents/next
NeAI  -> GET  /api/session          共有状態 (カーソル位置 + 画面メタ)
NeAI  -> GET  /api/screen           共有画面 PNG
NeAI  -> POST /api/actions          1 手操作
NeAI  -> POST /api/plans            複数手操作
```

接続用クライアント: [`neai_client.py`](neai_client.py)

### 共有セッション

```json
GET /api/session?scale=0.5
{
  "mode": "shared_desktop",
  "frameSeq": 12,
  "screen": { "width": 960, "height": 540, "scale": 0.5, "imageUrl": "/api/screen?scale=0.5" },
  "cursor": { "x": 640, "y": 450 },
  "coordinateSpace": "shared_screen_pixels",
  "armed": true
}
```

`scale` で縮小キャプチャを指定できます。NeAI の視覚処理向けです。

### 1 手操作

```json
POST /api/actions
{
  "action": { "type": "click", "x": 640, "y": 450, "button": "left" }
}
```

### 操作プラン

```json
POST /api/plans
{
  "actions": [
    { "type": "move", "x": 640, "y": 450, "durationMs": 180 },
    { "type": "click", "x": 640, "y": 450, "button": "left" }
  ]
}
```

利用可能なアクション: `move`, `click`, `double_click`, `drag`, `scroll`, `wait`

## 安全設計

- デフォルト DISARMED
- ローカルで `ARM` と入力しないと NeAI の操作は実行されない
- `127.0.0.1` のみ待ち受け

## 検証

```powershell
python -m unittest discover -s tests -v
```