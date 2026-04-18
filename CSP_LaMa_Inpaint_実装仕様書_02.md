# CSP LaMa Inpaint プラグイン 実装仕様書（改訂版）

## 目的

CLIP STUDIO PAINT のフィルタプラグインとして、現在選択中のラスターレイヤーと選択範囲を使い、ローカルで動作している SimpleLaMaEraser サーバーへ画像処理を依頼し、その結果をレイヤーへ反映する。

本プラグインは、CSP 側では複雑な画像処理を行わない。責務は以下に限定する。

- 操作対象レイヤーと選択範囲の検証
- レイヤー全体 RGBA 画像の取得
- 同サイズの二値マスク画像の生成
- Python サーバーとの HTTP 通信
- 返却された PNG のデコード
- 結果画像のレイヤーへの書き戻し

Crop、padding、LaMa 推論、マスク内外の合成はサーバー側が担当する。

---

## 目標と前提

### ユーザー操作
CSP の上部メニューから次を実行する。

- フィルタ > LaMa > inpaint

### 想定サーバー
既存の SimpleLaMaEraser サーバーを利用する。

既定の URL は以下とする。

- status: `http://127.0.0.1:7859/status`
- process: `http://127.0.0.1:7859/process`

### サーバー API 前提
- `/status` は JSON を返す
- `/process` は成功時 `image/png` を返す
- `/process` は失敗時 JSON を返す
- 送信するのは `multipart/form-data`
- 必須フィールドは `image` と `mask`

### プラグイン側の方針
- レイヤー全体を送る
- 同サイズの二値マスクを送る
- 返却 PNG はレイヤー全体サイズであることを前提にする
- 選択範囲外の保持はサーバーがすでに処理済みとみなす
- プラグイン側で複雑な部分合成はしない

### クライアント・サーバー間の二値化整合
- CSP 側では `select value > 0` をすべて 255、`select value == 0` を 0 とする完全二値化を行ってから送信する
- サーバー側の `>= 128 -> 255` しきい値処理は、誤差吸収用の安全策として存在してよい
- 正常系では、CSP 側から送るマスク値は 0 または 255 のみである

---

## ディレクトリ構成と主な改造対象

ベースは公式 SDK 付属の HSV サンプルを流用する。

### 主に改造するファイル
- `Source/HSV/PIHSVMain.cpp`
- `ResourceWin/HSV/HSV.rc`
- `ResourceWin/HSV/resource.h`
- `ProjectWin/HSV/HSV.vcxproj`

### そのまま使うファイル
- `PIFirstHeader.*`
- `PIDLLMainWin.cpp`
- `PISystemWin.h`
- `PITargetVersionWin.h`
- `TriglavPlugInSDK/*.h`
- `TriglavPluginWin.def`

### 削除候補または参照専用
- `PIHSVFilter.h`
  - HSV 演算ロジックは不要になる
  - すぐ削除せず、差分確認後に削除してよい

---

## モジュール GUID

### 必須
HSV サンプルの GUID は流用しないこと。

### 新規 GUID
実装では以下の GUID を使用すること。

`001A5334-9A2D-4586-A9F5-1F40A3855F0A`

### 反映箇所
- `PIHSVMain.cpp`
- `ModuleInitialize` 内の `moduleIDString`

### 注意
- HSV サンプルの GUID `A9EE0802-84E7-4847-87D8-9EBAC916EEE4` は使わない
- 同一 GUID のプラグインを複数インストールすると競合の原因になる

---

## プラグインの動作仕様

## 1. メニュー構造
CSP のメニュー上では以下の表示にする。

- フィルタカテゴリ: `LaMa`
- フィルタ名: `inpaint`

---

## 2. FilterInitialize の仕様

`kTriglavPlugInSelectorFilterInitialize` 時の設定は最小限にする。

### 必須設定
- フィルタカテゴリ名: `LaMa`
- フィルタ名: `inpaint`
- ターゲットレイヤー:
  - `kTriglavPlugInFilterTargetKindRasterLayerRGBAlpha`
- プレビュー:
  - `false`
- `setUseBlankImage`:
  - `false`

### 重要方針
- HSV サンプルのような色相・彩度・明度のプロパティ UI は作らない
- フィルタの常設 UI は作らない
- `SetCanPreview(true)` は使わない
- プロパティコールバックも不要

### 理由
- 今回の処理は外部サーバー通信を含み重い
- プレビュー UI の再計算ループと相性が悪い
- 過去の「操作パネルがすぐ閉じる」問題を避けるため
- サーバー設定は CSP のフィルタ UI ではなく、必要時だけ独自ダイアログで扱う
- サーバーが完成済み RGBA を返す前提なので、destination は元画像コピー開始で問題ない

---

## 3. FilterRun の仕様

`kTriglavPlugInSelectorFilterRun` が本体となる。

FilterRun は以下の順で処理する。

### 3-1. 前提確認
最初に以下を確認する。

1. サーバーへ接続できるか
2. 現在の対象がラスターレイヤーか
3. 選択範囲が存在するか
4. レイヤーマスク選択状態ではないか
5. Alpha lock 状態が致命的な問題にならないか必要に応じて確認する
6. 初版の制約を満たすレイヤーであるか

### 初版の対応範囲制約
初版では、以下の条件を満たす場合のみ正式対応とする。

- キャンバス全体サイズのラスターレイヤー
- レイヤー原点が `(0,0)` のラスターレイヤー

### 理由
- `getLayerOriginProc` はレイヤー原点を返す
- `getSelectAreaRectProc` はキャンバス座標系
- offscreen / bitmap 操作はレイヤーローカル座標を意識する必要がある
- 原点ズレ補正を初版から完全実装するとバグ源になりやすい

### エラー時の扱い
- いずれかが満たされなければ処理を中止
- ユーザーにはメッセージボックス等で理由を表示
- destination には何も書かない
- `result = kTriglavPlugInCallResultSuccess` にするか `Failed` にするかは、CSP 側の UX を見て調整する
- 初版では「処理自体は中止したがクラッシュではない」扱いを優先し、必要なら success 終了でもよい

### `FilterRunProcess(Start)` について
- 事前検証で弾くケースでは `FilterRunProcess(Start)` を呼ばずに終了する設計でもよい
- ただし、このときの CSP 上の挙動は実機で確認すること
- 実機で問題があれば、最小限の Start/End 呼び出しを追加すること

---

## 4. 接続確認仕様

### 接続先
まず保存済みのサーバー URL を使って `/status` にアクセスする。

### 成功条件
- HTTP レスポンス受信成功
- ステータスコード 200
- JSON を受け取れること

### 失敗時
接続できない場合は、URL 修正ダイアログを表示する。

### URL 修正ダイアログ仕様
独自の Win32 モーダルダイアログを使う。

表示内容:
- エラーメッセージ
- 現在の URL
- 編集可能な URL 入力欄
- 再接続ボタン
- キャンセルボタン

### 挙動
- 再接続成功なら、その URL を保存し処理を続行
- 再接続失敗なら、再度エラー表示
- キャンセルなら処理終了

### 重要方針
- URL 設定のために CSP のフィルタプロパティ UI は使わない
- URL はプラグイン側設定ファイルに保存する

---

## 5. URL 設定の保存仕様

初版ではシンプルなローカル設定ファイルを使う。

### 推奨
- INI
- JSON
- 単純なテキスト設定

### 保存項目
最低限、以下を保存する。

- server_base_url

### 例
- `http://127.0.0.1:7859`

### URL 組み立て
- status = base_url + `/status`
- process = base_url + `/process`

### 方針
- 末尾スラッシュ有無に注意して正規化すること

---

## 6. 選択範囲の扱い

### 基本方針
- 選択範囲なしならエラー
- ぼかし付き選択があっても、プラグイン側で二値化する
- 選択された画素は白
- 選択されていない画素は黒

### 選択範囲なし判定
- まず `hasSelectAreaOffscreenProc` を使って有無を判定する
- false なら「範囲選択が必要です」で終了する
- 念のため `getSelectAreaOffscreenProc` の結果が NULL でないことも確認してよい

### 二値化ルール
- `select value > 0` なら 255
- `select value == 0` なら 0

### 理由
- LaMa サーバー側は二値マスク運用
- 中間値のやわらかい境界は今回は捨てる

---

## 7. 画像取得仕様

### 送信する画像
- 操作中のラスタレイヤー全体を RGBA 相当画像として取得する

### 取得元
- `sourceOffscreenObject`

### 書き戻し先
- `destinationOffscreenObject`

### 実装方針
HSV サンプルのような「ブロックごとのその場書き換え」ではなく、いったん bitmap に転送してから扱う。

### copyMode に関する重要注意
SDK のヘッダだけでは、`getBitmapProc` / `setBitmapProc` が 1 回のコールで RGBA を完全取得・完全書き戻しできるか断定しないこと。

### 実装前の検証項目
最初に以下を確認すること。

1. `CopyModeNormal` で期待どおり RGBA 相当が取れるか
2. 取れない場合、`CopyModeImage` で RGB を取得する
3. 別途 `CopyModeAlpha` で Alpha を取得する
4. 取得結果を結合して RGBA バッファを構築する

### 推奨フロー
1. `sourceOffscreen` 全体サイズを取得
2. 同サイズの bitmap を作成
3. `getBitmapProc` で offscreen → bitmap
4. bitmap の画素データを RGBA バッファへ変換
5. 必要なら RGB と Alpha を別取得して結合する

### 重要
- 元画像はレイヤー全体
- Crop はしない
- レイヤー丸ごと送る

---

## 8. マスク生成仕様

### 入力元
- `selectAreaOffscreenObject`

### 生成物
- レイヤー全体と同サイズの 8bit 1ch マスク

### 値
- 選択あり: 255
- 選択なし: 0

### 実装方針
以下のどちらでもよい。

1. `selectAreaOffscreen` を bitmap 化して 1ch 相当バッファを組み立てる
2. ブロック走査で `getBlockSelectAreaProc` を使って全サイズマスクを作る

### 推奨
第1版では、実装が簡単なら bitmap ベース、難しければブロック走査でもよい。

### 重要
- 送るマスクはレイヤー全体サイズ
- サーバーに合わせて最終的に PNG 化する
- 初版は origin `(0,0)` 制約のもとで座標ズレを避ける

---

## 9. PNG 化仕様

### image
- RGBA PNG

### mask
- 8bit grayscale PNG

### 要件
- 画像サイズは完全一致
- 可能ならメモリ上で encode する
- 一時ファイルをディスクへ書かない

### 使用候補
- WIC
- GDI+
- stb_image_write のような軽量ライブラリ
- libpng

### 推奨
Windows 標準寄りで済ませるなら WIC を優先してよい。

---

## 10. HTTP 通信仕様

### リクエスト先
- `POST {base_url}/process`

### Content-Type
- `multipart/form-data`

### フィールド
- `image`
- `mask`

### 成功条件
- HTTP 200
- `Content-Type` が `image/png` で始まる

### 失敗条件
- 通信失敗
- 4xx / 5xx
- JSON エラー
- PNG 以外の返却

### 失敗時
- エラーメッセージをユーザーに表示
- レイヤーを書き換えない

### 実装候補
- WinHTTP 推奨

### multipart/form-data の重要注意
WinHTTP は multipart/form-data を自動生成しない前提で実装すること。

### 必須実装事項
- boundary を自前で生成する
- 各パートのヘッダーを自前で組み立てる
- CRLF を厳密に扱う
- 最後の終端 boundary を正しく付ける

### 推奨
- HTTP 部分は `HttpClientWin.*` のような別モジュールへ分離する
- 最初に multipart 単体の疎通テストを行う

### 重要方針
- 初版では URL 固定ベース + 設定ファイル
- CSP 側にはサーバー LAN 設定 UI を持たせない

---

## 11. 待ち時間中の実行モデル

### 重要方針
HTTP 通信を FilterRun のメインスレッドで長時間ブロックしない。

### 推奨モデル
- worker thread でサーバー通信を実行
- FilterRun 側は待機ループで定期的にホストへ進捗通知
- その待機中に `TriglavPlugInFilterRunProcess(...Continue...)` を呼ぶ
- キャンセル要求が来たら worker の結果を無視して終了する

### 理由
- ホストに進捗を返すため
- 「固まったように見える」状態を減らすため
- キャンセル対応のため

### 注意
- サーバー側処理そのものの中断までは初版では不要
- CSP 側で結果貼り戻しをやめるだけでよい

---

## 12. 進捗表示仕様

### 基本方針
自前のローディングサークルをフィルタ UI に出すことは初版では行わない。

### 利用する仕組み
- `TriglavPlugInFilterRunSetProgressTotal`
- `TriglavPlugInFilterRunSetProgressDone`
- `TriglavPlugInFilterRunProcess`

### 進捗フェーズ例
総数を 5 として、例えば以下のように進める。

1. 事前検証
2. 画像取得
3. PNG 生成
4. サーバー通信待ち
5. 書き戻し完了

### 待機中
通信待機中も一定間隔で `FilterRunProcess(...Continue...)` を呼ぶこと。

### 補助
必要なら Windows の待機カーソルを併用してよい。

---

## 13. キャンセル仕様

### ホスト側から終了指示が来た場合
- worker thread の結果を使わない
- destination を更新しない
- そのまま処理終了

### サーバー結果があとから返ってきた場合
- 無視してよい
- 初版ではサーバーへキャンセル通知は不要

### 重要
- 「処理中にユーザーが別の編集をして、あとから上書きされる」危険を減らすため、キャンセル時は結果を書き戻さない

---

## 14. 書き戻し仕様

### サーバーから返るもの
- レイヤー全体サイズの RGBA PNG

### 検証
書き戻し前に以下を確認する。

- decode 成功
- width/height が元レイヤーと一致
- RGBA として扱えること

### 書き戻し方法
1. PNG を decode
2. bitmap を作成
3. decode 結果を bitmap に格納
4. `setBitmapProc` で destination offscreen へ全面コピー
5. `updateDestinationOffscreenRect` で更新通知

### Alpha に関する注意
- `offscreenService2->getBitmapNormalAlphaChannelIndexProc` の確認が必要になる可能性がある
- 実行時に RGB 並びを取得するのと同様、Alpha の扱いも検証すること
- 初版では「必要なら offscreenService2 を参照する」前提で実装する

### 重要
- 部分貼り戻しはしない
- サーバーがすでにマスク外保持済みとみなす
- 左上 origin の追加補正は初版では行わない
- その代わり、初版は origin `(0,0)` の全面ラスタレイヤーに対応範囲を制限する
- `getLayerOriginProc` はログ取得用に呼んでよい

---

## 15. 失敗時メッセージ仕様

初版ではシンプルにメッセージボックスでよい。

### 最低限必要なエラー
- サーバーに接続できません
- サーバー URL が不正です
- ラスターレイヤー以外は対象外です
- 範囲選択が必要です
- レイヤー原点 `(0,0)` の全面ラスタレイヤーのみ対応です
- レイヤーマスク選択中は使用できません
- サーバー処理に失敗しました
- サーバーから不正な画像が返りました
- 返却画像サイズが一致しません

### 表示方針
- 1 回の失敗につき 1 ダイアログ
- 詳細ログは必要に応じて debug 出力へ

---

## 16. ファイル単位の改造指針

## `PIHSVMain.cpp`
全面改造対象。

### 残すもの
- `TriglavPluginCall` の骨格
- `ModuleInitialize`
- `ModuleTerminate`
- `FilterInitialize`
- `FilterRun`
- `FilterTerminate`

### 捨てるもの
- HSV 用 itemKey
- HSV 用プロパティコールバック
- HSV パラメータ管理
- `PIHSVFilter::SetHSV8` 系の per-pixel ロジック
- プレビュー再計算ループ

### 追加するもの
- 新 GUID の設定
- サーバー URL 管理
- `/status` 接続確認
- URL 入力ダイアログ呼び出し
- RGBA 抽出
- 二値マスク生成
- PNG encode
- multipart/form-data 送信
- PNG decode
- 書き戻し
- worker thread + progress polling

---

## `resource.h`
以下を追加する可能性がある。

- LaMa 用カテゴリ名
- LaMa 用フィルタ名
- 接続失敗ダイアログのリソース ID
- URL 入力欄やボタンの ID

HSV 用文字列 ID は整理して削減してよい。

---

## `HSV.rc`
以下を実装する。

- 文字列テーブル
  - `LaMa`
  - `inpaint`
  - エラーメッセージ
- 必要なら独自ダイアログリソース
  - URL 入力ダイアログ

---

## `HSV.vcxproj`
必要に応じて以下を追加。

- WinHTTP 依存
- WIC/GDI+ など PNG encode/decode に必要なリンク設定
- 追加ソースファイル

---

## 17. 補助クラス・関数の推奨分離

`PIHSVMain.cpp` 1 ファイルに全部詰め込まず、必要なら補助ファイルを追加してよい。

### 推奨分離
- `ServerConfig.*`
  - URL の読込保存
- `HttpClientWin.*`
  - WinHTTP 通信
- `PngCodecWin.*`
  - PNG encode/decode
- `OffscreenUtils.*`
  - bitmap 化、RGBA 抽出、書き戻し
- `MaskUtils.*`
  - 選択範囲から二値マスク生成
- `DialogUtilsWin.*`
  - URL 入力ダイアログ、メッセージ表示

### 重要
初版で無理に分割しすぎなくてもよいが、少なくとも HTTP と PNG はロジックを分けたほうが後で楽。

---

## 18. 実装前の検証項目

実装開始直後に、以下を優先的に検証すること。

1. `getBitmapProc` / `setBitmapProc` の copyMode ごとの実際の挙動
2. RGBA 一括取得が可能か、RGB/Alpha 別取得が必要か
3. `offscreenService2` の Alpha 関連 API が必要か
4. `FilterRunProcess(Start)` を呼ばずに early return したときの CSP の挙動
5. WinHTTP multipart/form-data の疎通
6. origin `(0,0)` 制約下でマスク位置がずれないこと

---

## 19. 受け入れ条件

以下を満たしたら最低限の実装完了とみなす。

1. メニュー `フィルタ > LaMa > inpaint` が表示される
2. ModuleInitialize に新 GUID が設定されている
3. ラスターレイヤー以外では処理を拒否する
4. 範囲選択がない場合は処理を拒否する
5. `/status` でサーバー接続確認を行う
6. 接続失敗時に URL 修正ダイアログを出せる
7. レイヤー全体 RGBA 相当 PNG をサーバーへ送れる
8. 同サイズの二値マスク PNG をサーバーへ送れる
9. `/process` 成功時の PNG を decode して destination に書き戻せる
10. 返却画像サイズが一致しない場合は反映しない
11. 通信待機中にホスト進捗を返せる
12. キャンセル時は結果を書き戻さない
13. フィルタの常設プロパティ UI を持たない
14. プレビュー再計算を行わない
15. 初版では origin `(0,0)` の全面ラスタレイヤーで正常動作する

---

## 20. 実装優先順位

### 第1段階
- GUID 変更
- フィルタ名変更
- UI を最小化
- サーバー接続確認
- 画像送信
- 結果書き戻し
- copyMode 検証

### 第2段階
- URL 入力ダイアログ
- 設定保存
- worker thread + progress polling
- キャンセル対応

### 第3段階
- エラーメッセージ整理
- 補助クラス分離
- ログ強化
- origin 補正の将来拡張

---

## 21. 今回やらないこと

初版では以下は対象外とする。

- CSP 側での Crop 実装
- CSP 側での padding 処理
- マスク中間値の保持
- サーバー LAN 設定の CSP 側 UI
- 高度なフィルタダイアログ
- 自前ローディングサークル UI
- サーバー側キャンセル API
- レイヤー差分マージ
- 複数レイヤー処理
- ベクターレイヤー対応
- レイヤーマスク直接処理
- origin `(0,0)` 以外のレイヤー対応

---

## 22. 実装メモ

- HSV サンプルは「画素単位フィルタ + プレビュー再計算」の見本であり、今回は処理モデルが異なる
- ただし `TriglavPluginCall` の骨格と FilterRun のホスト連携はそのまま流用価値がある
- 位置関係依存の処理では bitmap への転送が推奨されているため、LaMa 連携も bitmap ベースで組む
- 初版は「安定して1回動くこと」を優先し、UI の豪華さより堅牢性を取る
- 公開情報だけでは copyMode の細部が断定しにくいため、最初に小さな検証コードで確かめること
