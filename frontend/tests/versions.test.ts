import assert from 'node:assert/strict';
import { test } from 'node:test';
import { newerVersion, buildState, buildReleaseUrl } from '../src/lib/versions.ts';

test('stable release comparison handles major, minor, patch and multi-digit versions', () => {
	for (const next of ['1.0.0', '0.2.0', '0.1.1', 'v0.10.0']) {
		assert.equal(newerVersion(next, '0.1.0'), true);
	}
	for (const next of ['0.1.0', '0.0.9', '0.2.0-beta.1', 'invalid', '0.01.1']) {
		assert.equal(newerVersion(next, '0.1.0'), false);
	}
	assert.equal(newerVersion('0.9.0', '0.10.0'), false);
	assert.equal(newerVersion('1.0.0', 'dev'), false);
});

test('build states distinguish stable, outdated and experimental installations', () => {
	assert.equal(buildState('0.1.0', 'abc', 'v0.1.0'), 'current');
	assert.equal(buildState('0.1.0', 'abc-dirty', '0.1.0'), 'experimental');
	assert.equal(buildState('0.2.0', 'abc', '0.1.0'), 'experimental');
	assert.equal(buildState('0.1.0', 'abc-dirty', '0.2.0'), 'behind');
	assert.equal(buildState('0.1.0', null, '0.2.0'), 'behind');
	assert.equal(buildState('dev', null, '0.1.0'), 'experimental');
	assert.equal(buildState('0.1.0', null, null), 'unknown');
	assert.equal(buildState('0.1.0', 'abc-dirty', null), 'experimental');
});

test('release links require a matching confirmed release', () => {
	const url = 'https://github.com/Xharos/sophikron/releases/tag/v0.1.0';
	assert.equal(buildReleaseUrl('0.1.0', 'v0.1.0', url), url);
	assert.equal(buildReleaseUrl('0.2.0', '0.1.0', url), null);
	assert.equal(buildReleaseUrl('0.0.9', '0.1.0', url), null);
	assert.equal(buildReleaseUrl('0.1.0', null, null), null);
});
