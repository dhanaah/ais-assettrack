// postinstall: keep only the Latin text-recognition model of @react-native-ml-kit/text-recognition (pallet numbers are
// Latin letters + digits). The package bundles Chinese / Japanese / Korean / Devanagari models too (~30 MB of APK).
// Also gives the old library a namespace for the Android Gradle plugin 8. Idempotent. Developed by DT
const fs = require('fs'); const path = require('path');
const base = path.join(__dirname, '..', 'node_modules', '@react-native-ml-kit', 'text-recognition', 'android');
const gradle = path.join(base, 'build.gradle');
const java = path.join(base, 'src', 'main', 'java', 'com', 'rnmlkit', 'textrecognition', 'TextRecognitionModule.java');
if (!fs.existsSync(gradle) || !fs.existsSync(java)) { console.log('mlkit patch: package not installed, skipped'); process.exit(0); }
let g = fs.readFileSync(gradle, 'utf8');
g = g.replace(/^\s*implementation 'com\.google\.mlkit:text-recognition-(chinese|devanagari|japanese|korean):[^']+'\s*$/gm, '');
if (!/namespace\s+"com\.rnmlkit\.textrecognition"/.test(g)) g = g.replace(/android\s*\{/, 'android {\n    namespace "com.rnmlkit.textrecognition"');
fs.writeFileSync(gradle, g);
let j = fs.readFileSync(java, 'utf8');
j = j.replace(/^import com\.google\.mlkit\.vision\.text\.(chinese|devanagari|japanese|korean)\..*$/gm, '');
j = j.replace(/return new (Chinese|Devanagari|Japanese|Korean)TextRecognizerOptions\.Builder\(\)\.build\(\);/g, 'return TextRecognizerOptions.DEFAULT_OPTIONS;');
fs.writeFileSync(java, j);
console.log('mlkit patch: Latin model only');
