# حزمة اختبار الصلاحية الشاملة — PS5 5.50 Arabi POC (مجانية 100%)

هذه الحزمة مصممة لاختبار **المعمارية الجديدة** على **أي لعبة PS4 (`CUSA*`) أو PS5 (`PPSA*`)** على تحديث **5.50** بدون كمبيوتر وبدون لينكس وبـ **0 ريال**.

## محتويات الحزمة
- `ps5_poc/arabi_scanner_poc.c`: **POC 2** — فاحص ومستخرج انتقائي عام يقرأ أي لعبة شغالة في `/mnt/sandbox/pfsmnt/` ويستخرج ملفات اللغة والخط فقط (بحد أقصى 150 MB للملف) ويصدر تقرير `/data/arabi_poc/scan_<TITLE_ID>.json`.
- `ps5_poc/arabi_afr_poc.c`: **POC 1** — نواة إعادة توجيه الملفات (`/app0/` ← `/data/arabi_mods/<TITLE_ID>/`) واختبار صلاحيات الكتابة والقراءة على 5.50.
- `cloud_worker/toolkit/safe_arabic_shaper_fixed.py` و `arabic_font_merger_fixed.py`: النسخة المصححة من أدوات مشروع عبدالله السبيعي (إصلاح حد الـ 27 وسم، حماية `%s`/`%d`/`[BTN]`، قياس التفاف الأسطر بدون وسوم، ومنع انهيار خطوط `.otf`).
- `cloud_worker/translate_free.py`: **POC 3** — عامل سحابي مجاني بوضعين: تقسيم للمحادثة (`split`) أو `Gemini Flash-Lite Free Tier`.
- `.github/workflows/build_ps5_poc.yml`: يبني ملفات الـ `.elf` للـ PS5 مجاناً على GitHub بدون كمبيوتر.

## خطوات التشغيل والتجربة أول ما ترجع للبيت (بدون كمبيوتر)
1. **إنشاء المستودع والبناء المجاني:**
   - افتح حسابك في GitHub من الجوال، أنشئ مستودع جديد (مثلاً `ps5-arabi-poc`) وارفع محتويات هذا الـ ZIP.
   - ادخل تبويب **Actions** ← شغّل **Build PS5 5.50 Arabi POC (Free)** ← حمّل ملف النتيجة `ps5-arabi-poc-550-elfs.zip` (يحتوي على `arabi_scanner_poc.elf` و `arabi_afr_poc.elf`).
2. **تشغيل POC 2 على أي لعبة (رايمان PS4 + أي لعبة PS5 عندك):**
   - فعّل تهكير **5.50 (`etaHEN` + `elfldr` على منفذ `9021`)**.
   - شغّل اللعبة وخلّها شغالة (لا تقفلها).
   - أرسل `arabi_scanner_poc.elf` إلى الـ PS5 على منفذ `9021` (نفس طريقة إرسال البايلودات).
   - افتح `/data/arabi_poc/scanner.log` و `/data/arabi_poc/scan_<TITLE_ID>.json` وشوف:
     - هل طلع `PASS`؟
     - كم حجم اللعبة الكامل مقارنة بحجم ملفات اللغة المستخرجة فقط؟
3. **تشغيل POC 1 (اختبار صلاحيات ومسار إعادة التوجيه):**
   - أرسل `arabi_afr_poc.elf` على منفذ `9021`، وتأكد من ظهور `[PASS]` في `/data/arabi_poc/afr_poc.log`.
4. **تشغيل POC 3 (العامل السحابي المجاني):**
   - من GitHub ← تبويب **Actions** ← شغّل **Cloud Localization Worker POC (0 SAR)** على `sample_strings_en.json` بوضع `split` (أو `gemini` بعد إضافة `GEMINI_API_KEY` في Secrets).

## النتيجة المطلوبة بعد التجربة
أرسل لي محتوى `scanner.log` و `scan_<TITLE_ID>.json` لأول لعبتين تجربهما (رايمان + لعبة PS5)، وبناءً على النتيجة الحقيقية ننتقل فوراً لبناء طبقة الحقن الحي داخل اللعبة (`etaHEN SPRX Hook`) والتطبيق النهائي.
