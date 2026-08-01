"""課程專屬的詞彙模組。

框架不認識任何主題，這裡的內容由 course.config.json 的 taxonomy 指定：

- facets     用來做分面篩選的實體（本課程是肌群）
- categories 把個別項目歸類到有文獻可掛的類別（本課程是動作類別）

換主題時整個資料夾都可以重寫，或在 config 拿掉 taxonomy 直接不用。
"""
