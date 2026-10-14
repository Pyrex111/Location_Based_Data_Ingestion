const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function portal({ location = 'allowed', responses = [] } = {}) {
  const elements = Object.fromEntries(
    ['dropzone', 'fileNames', 'manualCityInput', 'uploadButton', 'manual_city'].map((id) => [id, {
      style: { display: 'none' }, value: '', children: [], listeners: {}, disabled: false,
      addEventListener(event, listener) { this.listeners[event] = listener; },
      appendChild(child) { this.children.push(child); },
      set innerHTML(value) { if (value === '') this.children = []; },
    }]),
  );
  const requests = [];
  const alerts = [];
  const navigator = location === 'unavailable' ? {} : {
    geolocation: {
      getCurrentPosition(success, failure) {
        if (location === 'denied') failure({ message: 'Location denied' });
        else success({ coords: { latitude: 48.45, longitude: -123.38 } });
      },
    },
  };
  const context = vm.createContext({
    document: { getElementById: (id) => elements[id], createElement: () => ({ textContent: '' }) },
    navigator,
    alert: (message) => alerts.push(message),
    FormData: class {
      constructor() { this.entries = []; }
      append(name, value) { this.entries.push([name, value]); }
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return { ok: response?.ok ?? true, json: async () => response?.data ?? { message: 'Uploaded' } };
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/upload.js'), 'utf8'), context);
  const drop = () => elements.dropzone.listeners.drop({
    preventDefault() {}, dataTransfer: { files: [{ name: 'sample.txt' }] },
  });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  return { elements, requests, alerts, drop, settle };
}

test('automatic location upload sends file and coordinates, then clears the list', async () => {
  const p = portal();
  p.drop();
  await p.settle();
  assert.equal(p.requests[0].url, '/upload');
  assert.deepEqual(p.requests[0].options.body.entries.map(([key]) => key), ['files[]', 'latitude', 'longitude']);
  assert.equal(p.elements.fileNames.children.length, 0);
});

test('denied location keeps files and supports a manual-city upload', async () => {
  const p = portal({ location: 'denied' });
  p.drop();
  assert.equal(p.elements.manualCityInput.style.display, 'block');
  assert.equal(p.elements.fileNames.children.length, 1);
  p.elements.manual_city.value = 'Victoria';
  p.elements.uploadButton.listeners.click();
  await p.settle();
  assert.equal(p.requests[0].options.body.entries.find(([key]) => key === 'manual_city')[1], 'Victoria');
  assert.equal(p.elements.fileNames.children.length, 0);
});

test('a geocoding failure retains files for successful manual retry', async () => {
  const p = portal({ responses: [{ ok: false, data: { manual_city_required: true, message: 'Enter city' } }] });
  p.drop();
  await p.settle();
  assert.equal(p.elements.manualCityInput.style.display, 'block');
  assert.equal(p.elements.fileNames.children.length, 1);
  p.elements.manual_city.value = 'Toronto';
  p.elements.uploadButton.listeners.click();
  await p.settle();
  assert.equal(p.requests.length, 2);
  assert.equal(p.elements.fileNames.children.length, 0);
});

test('an S3 error retains files and the manual input', async () => {
  const p = portal({ location: 'denied', responses: [{ ok: false, data: { message: 'S3 failed' } }] });
  p.drop();
  p.elements.manual_city.value = 'Victoria';
  p.elements.uploadButton.listeners.click();
  await p.settle();
  assert.equal(p.elements.fileNames.children.length, 1);
  assert.equal(p.elements.manualCityInput.style.display, 'block');
  assert.equal(p.elements.uploadButton.disabled, false);
  assert.equal(p.alerts.at(-1), 'S3 failed');
});

test('missing browser geolocation exposes manual input and rejects a blank city', () => {
  const p = portal({ location: 'unavailable' });
  p.drop();
  assert.equal(p.elements.manualCityInput.style.display, 'block');
  p.elements.uploadButton.listeners.click();
  assert.equal(p.requests.length, 0);
  assert.equal(p.alerts.at(-1), 'Please enter a city name.');
});

test('network failure keeps files available for retry', async () => {
  const p = portal({ responses: [new Error('Network unavailable')] });
  p.drop();
  await p.settle();
  assert.equal(p.elements.fileNames.children.length, 1);
  assert.equal(p.elements.uploadButton.disabled, false);
  assert.equal(p.alerts.at(-1), 'Error: Network unavailable');
});
