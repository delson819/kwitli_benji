const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

const source = ts.createSourceFile('App.tsx', fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let pickPhoto = '';
let replaceCookProfilePhoto = '';
let choosePhoto = '';

function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'pickMerchantImage') {
    pickPhoto = node.getText(source);
  }
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'replaceCookProfilePhoto') replaceCookProfilePhoto = node.getText(source);
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'choosePhoto') choosePhoto = node.getText(source);
  ts.forEachChild(node, visit);
}

visit(source);

assert.ok(pickPhoto.includes('imagePickerOpen.current'), 'Photo picker must be guarded against duplicate launches');
assert.ok(pickPhoto.includes('allowsEditing: false'), 'Merchant photo picker must not enable editing/crop');
assert.ok(pickPhoto.includes('allowsMultipleSelection: false'), 'Merchant photo picker must stay single-selection');
assert.ok(!pickPhoto.includes('selectionLimit'), 'Merchant photo picker must avoid multi-select-only selectionLimit for the minimal iOS flow');
assert.ok(!pickPhoto.includes('presentationStyle'), 'Merchant photo picker must avoid forcing a custom iOS presentation style');
assert.ok(pickPhoto.includes('preferredAssetRepresentationMode'), 'Merchant photo picker must request a compatible iOS asset representation');
assert.ok(pickPhoto.indexOf('setCookError(null)') < pickPhoto.indexOf('requestCameraPermissionsAsync'), 'Photo errors must clear before permission checks');
assert.ok(pickPhoto.includes('PHOTO FLOW START'), 'Photo flow start must identify source and target');
assert.ok(pickPhoto.includes('error.imagePermission'), 'Permission errors must have a distinct message');
assert.ok(pickPhoto.includes('prepareMerchantImage(asset, source, target)'), 'Picked merchant photos must be prepared before preview/upload');
assert.ok(pickPhoto.includes('finally'), 'Photo picker launch guard must always be released');
assert.ok(replaceCookProfilePhoto.includes('pickMerchantImage(camera, "establishment")'), 'Existing establishment logo changes must reuse merchant image preparation');
assert.ok(choosePhoto.includes('target === "profile" ? "establishment" : "article"'), 'New establishment preview must reuse merchant image preparation');

let prepareMerchantImage = '';
let isHeicOrHeif = '';
function visitAll(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'prepareMerchantImage') prepareMerchantImage = node.getText(source);
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'isHeicOrHeif') isHeicOrHeif = node.getText(source);
  ts.forEachChild(node, visitAll);
}
visitAll(source);
assert.ok(isHeicOrHeif.includes('heic') && isHeicOrHeif.includes('heif'), 'HEIC and HEIF must be detected');
assert.ok(prepareMerchantImage.includes('const originalWasHeic = isHeicOrHeif(asset)'), 'Original image format must be detected before optimization');
assert.ok(prepareMerchantImage.includes('logMerchantImage("ORIGINAL", asset, source, target)'), 'Original image metadata must be logged');
assert.ok(prepareMerchantImage.includes('logMerchantImage("NORMALIZED", normalized, source, target)'), 'Normalized image metadata must be logged');
assert.ok(prepareMerchantImage.includes('CONVERSION SUCCESS') && prepareMerchantImage.includes('CONVERSION ERROR'), 'Conversion outcome must be logged');
assert.ok(prepareMerchantImage.includes('error.imageConversion'), 'Conversion errors must have a distinct message');
assert.ok(prepareMerchantImage.includes('ImageManipulator.manipulateAsync'), 'HEIC/HEIF must be converted with ImageManipulator');
assert.ok(prepareMerchantImage.includes('SaveFormat.JPEG'), 'HEIC/HEIF conversion must write real JPEG');
assert.ok(prepareMerchantImage.includes('compress: 0.8'), 'Merchant images must be compressed before upload');
assert.ok(prepareMerchantImage.includes('MAX_MERCHANT_PHOTO_DIMENSION'), 'Merchant images must be bounded before upload');
assert.ok(prepareMerchantImage.includes('mimeType: "image/jpeg"'), 'Converted upload MIME must be image/jpeg');
assert.ok(prepareMerchantImage.includes('fileName: jpegFileName(asset)'), 'Converted upload filename must use .jpg');

const appText = fs.readFileSync(`${__dirname}/../App.tsx`, 'utf8');
const apiText = fs.readFileSync(`${__dirname}/services/api.ts`, 'utf8');
const fr = require('../locales/fr.json');
const es = require('../locales/es-CO.json');
for (const key of ['error.imagePermission', 'error.imageConversion', 'error.imageFormat', 'error.imageUpload']) {
  assert.ok(fr[key] && es[key], `${key} must exist in both locales`);
}
assert.ok(appText.includes('error.imageFormat') && appText.includes('error.imageUpload'), 'Upload failures must distinguish unsupported format from other failures');
assert.ok(!appText.includes('t("error.image")'), 'The old shared image message must not be used');
for (const marker of ['UPLOAD START', 'UPLOAD HTTP STATUS', 'UPLOAD SUCCESS', 'UPLOAD ERROR']) {
  const expectedCount = marker === 'UPLOAD ERROR' ? 4 : 2;
  assert.equal(apiText.split(`"${marker}"`).length - 1, expectedCount, `${marker} must be logged for both photo endpoints`);
}

console.log('Merchant photo picker single-launch, camera JPEG preparation and guard release: PASS');
