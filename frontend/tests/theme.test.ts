import assert from 'node:assert/strict';
import { test } from 'node:test';
import { themePreference, themedHtml, themeCookieValue } from '../src/lib/theme.ts';
import { contrastRatio, readableColor } from '../src/lib/colors.ts';
import { colorForeground } from '../src/lib/lessons.ts';

test('theme cookies accept only explicit preferences and default to the device', () => {
	for (const value of [null, undefined, '', 'SYSTEM', '<script>', 'dark" onload="alert(1)']) {
		assert.equal(themePreference(value), 'system');
		assert.equal(themedHtml('<html data-theme="system">', value), '<html data-theme="system">');
	}
	for (const value of ['light', 'system', 'dark'] as const) {
		assert.equal(themePreference(value), value);
		assert.equal(
			themedHtml('<html data-theme="system"><body>system</body>', value),
			`<html data-theme="${value}"><body>system</body>`
		);
		assert.equal(
			themeCookieValue(value, true),
			`sophikron_theme=${value}; Path=/; Max-Age=31536000; SameSite=Lax; Secure`
		);
		assert.equal(themeCookieValue(value, false).includes('Secure'), false);
	}
});

test('custom colored text and solid icon backgrounds retain at least 4.5:1 contrast', () => {
	const colors = [
		'#000000',
		'#ffffff',
		'#ffff00',
		'#777777',
		'#ff0000',
		'#00ff00',
		'#0000ff',
		'#244bc1',
		'#67449a'
	];
	for (let red = 0; red <= 255; red += 51) {
		for (let green = 0; green <= 255; green += 51) {
			for (let blue = 0; blue <= 255; blue += 51) {
				colors.push(
					'#' + [red, green, blue].map((channel) => channel.toString(16).padStart(2, '0')).join('')
				);
			}
		}
	}
	for (const color of colors) {
		assert.ok(contrastRatio(color, colorForeground(color)) >= 4.5, color);
		for (const background of ['#f7f8fa', '#1b2532']) {
			assert.ok(
				contrastRatio(readableColor(color, background), background) >= 4.5,
				`${color} on ${background}`
			);
		}
	}
	assert.equal(readableColor('#244bc1', '#f7f8fa'), '#244bc1');
});
