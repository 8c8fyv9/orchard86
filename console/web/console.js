// SPDX-License-Identifier: GPL-3.0-or-later
import RFB from '/novnc/core/rfb.js';

const screen = document.querySelector('#screen');
const status = document.querySelector('#status');
const connection = document.querySelector('#connection');
const fullscreen = document.querySelector('#fullscreen');
const switchApp = document.querySelector('#switch-app');
const forceQuit = document.querySelector('#force-quit');
const statsButton = document.querySelector('#performance');
const statsPanel = document.querySelector('#stream-stats');
const statsFields = ['rate', 'down', 'size', 'age'].map(id => document.querySelector('#stats-' + id));
let stats = null;
let timer = null;
let rfb = null;

function baseline() {
    if (stats) stats.sample = { at: performance.now(), draws: stats.draws, bytes: stats.bytes };
}

function renderStats() {
    const values = ['—', '—', '—', '—'];
    if (stats?.connected) {
        const now = performance.now();
        const sec = (now - stats.sample.at) / 1000;
        if (sec >= .2) {
            if (stats.canvas) values[0] = ((stats.draws - stats.sample.draws) / sec).toFixed(1) + ' 次/s';
            values[1] = ((stats.bytes - stats.sample.bytes) / sec / 1024).toFixed(1) + ' KiB/s';
            stats.sample = { at: now, draws: stats.draws, bytes: stats.bytes };
        }
        if (stats.canvas) values[2] = stats.canvas.width + ' × ' + stats.canvas.height;
        if (stats.lastDraw !== null) values[3] = ((now - stats.lastDraw) / 1000).toFixed(2) + ' s';
    }
    statsFields.forEach((field, i) => { field.textContent = values[i]; });
}

statsButton.onclick = () => {
    statsPanel.hidden = !statsPanel.hidden;
    statsButton.setAttribute('aria-expanded', String(!statsPanel.hidden));
    clearInterval(timer);
    if (!statsPanel.hidden) {
        baseline();
        renderStats();
        timer = setInterval(renderStats, 1000);
    }
    rfb?.focus();
};

function connect() {
    status.textContent = '正在连接…';
    connection.disabled = true;
    connection.textContent = '断开';
    const url = new URL('/ws', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const channel = new WebSocket(url.href, ['binary']);
    const metrics = { bytes: 0, draws: 0, lastDraw: null, canvas: null, connected: false };
    stats = metrics;
    baseline();
    channel.addEventListener('message', event => { metrics.bytes += event.data.byteLength; });
    const client = new RFB(screen, channel);
    rfb = client;
    let unsupportedAuth = false;
    client.scaleViewport = true;
    client.resizeSession = false;
    client.compressionLevel = 0;
    client.addEventListener('connect', () => {
        metrics.connected = true;
        baseline();
        // noVNC 1.6 draws damaged regions to this canvas with drawImage.
        // Observe only this context, without reading pixels or changing the render queue.
        const canvas = screen.querySelector('canvas');
        const context = canvas?.getContext('2d');
        if (context) {
            metrics.canvas = canvas;
            const drawImage = context.drawImage;
            context.drawImage = function (...args) {
                const result = drawImage.apply(this, args);
                metrics.draws++;
                metrics.lastDraw = performance.now();
                return result;
            };
        }
        status.textContent = '已连接';
        connection.disabled = switchApp.disabled = forceQuit.disabled = false;
        client.focus();
    });
    client.addEventListener('credentialsrequired', () => {
        unsupportedAuth = true;
        client.disconnect();
    });
    client.addEventListener('disconnect', (event) => {
        rfb = null;
        stats = null;
        if (!statsPanel.hidden) renderStats();
        status.textContent = unsupportedAuth ? '此测试版不支持 VNC 凭据' :
            (event.detail.clean ? '已断开' : '连接中断，请重试');
        connection.textContent = '连接';
        connection.disabled = false;
        switchApp.disabled = forceQuit.disabled = true;
    });
}

connection.onclick = () => rfb ? rfb.disconnect() : connect();
fullscreen.onclick = async () => {
    try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
    } catch (error) {
        console.warn('Fullscreen unavailable', error);
    }
    rfb?.focus();
};

const command = [0xffeb, 'MetaLeft'];
const option = [0xffe9, 'AltLeft'];
function sendChord(modifiers, key) {
    if (!rfb) return;
    for (const modifier of modifiers) rfb.sendKey(...modifier, true);
    rfb.sendKey(...key);
    for (const modifier of [...modifiers].reverse()) rfb.sendKey(...modifier, false);
    rfb.focus();
}
switchApp.onclick = () => sendChord([command], [0xff09, 'Tab']);
forceQuit.onclick = () => sendChord([command, option], [0xff1b, 'Escape']);
connect();
