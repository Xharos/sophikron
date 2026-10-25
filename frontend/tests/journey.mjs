/** Real HTTP journey against disposable services; no persistent installation is accepted. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

if (
	process.env.DB_NAME !== 'sophikron_test' ||
	process.env.DB_INTEGRATION !== '1' ||
	!process.env.BFF_TEST_URL
) {
	throw new Error('The BFF journey requires the disposable backend/run_tests.py environment.');
}
const base = process.env.BFF_TEST_URL;
const origin = 'http://localhost:3000';
const password = 'BffIntegrationPassword2026!';
const replacement = 'BffReplacementPassword2026!';
const bootstrap = (
	await readFile(`${process.env.SOPHIKRON_SECRETS_DIRECTORY}/bootstrap_password`, 'utf8')
).trim();
const jar = new Map();
async function request(path, data, suppliedOrigin = origin, json = false) {
	const headers = new Headers({ accept: json ? 'application/json' : 'text/html' });
	if (jar.size)
		headers.set('cookie', [...jar].map(([name, value]) => `${name}=${value}`).join('; '));
	if (data && suppliedOrigin) headers.set('origin', suppliedOrigin);
	if (json) headers.set('content-type', 'application/json');
	const response = await fetch(`${base}${path}`, {
		method: data ? 'POST' : 'GET',
		headers,
		body: data ? (json ? JSON.stringify(data) : new URLSearchParams(data)) : undefined,
		redirect: 'manual'
	});
	for (const cookie of response.headers.getSetCookie()) {
		const [pair] = cookie.split(';');
		const separator = pair.indexOf('=');
		if (/max-age=0/i.test(cookie)) jar.delete(pair.slice(0, separator));
		else jar.set(pair.slice(0, separator), pair.slice(separator + 1));
	}
	return response;
}
function expectRedirect(response, location) {
	assert.equal(response.status, 303, `Expected redirect to ${location}, got ${response.status}`);
	assert.equal(response.headers.get('location'), location);
}
async function data(resource, values = {}) {
	const response = await request(
		`/dashboard/data?${new URLSearchParams({ resource, ...values })}`
	);
	assert.equal(response.status, 200, `Read ${resource} failed: ${await response.clone().text()}`);
	return response.json();
}
async function command(name, values = {}) {
	const response = await request(
		'/dashboard/command',
		{ command: name, ...values },
		origin,
		true
	);
	assert.equal(response.status, 200, `Command ${name} failed: ${await response.clone().text()}`);
	return response.json();
}
const login = (identifier, secret = password) =>
	request('/login', { identifier, password: secret });
const activation = (token, secret = password) =>
	request('/activate', { token, password: secret, confirmation: secret });

for (const path of ['/lessons', '/dashboard', '/admin', '/me'])
	expectRedirect(await request(path), '/login');
assert.equal((await request('/dashboard/data?resource=summary')).status, 401);
assert.equal(
	(await request('/dashboard/command', { command: 'createPromotion' }, origin, true)).status,
	401
);
for (const suppliedOrigin of [null, 'https://evil.example']) {
	assert.equal(
		(await request('/login', { identifier: 'unknown', password }, suppliedOrigin)).status,
		403
	);
}
expectRedirect(await login('verification_setup', bootstrap), '/');
expectRedirect(await request('/admin/users/new'), '/setup');
const setup = await request('/setup', {
	first_name: 'Alice',
	last_name: 'Martin',
	email: 'owner@example.org',
	password,
	confirmation: password
});
assert.equal(setup.status, 200);
const setupHtml = await setup.text();
const owner = setupHtml.match(/amart\d{3}/)?.[0];
assert.ok(owner, 'Setup must display the generated permanent username');
assert.equal(jar.size, 0);
expectRedirect(await login('owner@example.org'), '/');
assert.equal((await request('/dashboard')).status, 200);
expectRedirect(await request('/admin'), '/dashboard');
expectRedirect(await request('/admin/users/new'), '/dashboard?tab=accounts&create=account');
assert.ok((await (await request('/me')).text()).includes('Alice'));
const promotion = await command('createPromotion', {
	data: { year: 2026, identifier: 'PTSI', color: '#5566CC' }
});
const create = (first, last, email, roles, promotionIds = []) =>
	command('createUser', {
		data: {
			first_name: first,
			last_name: last,
			email,
			roles,
			promotion_ids: promotionIds
		}
	});
const student = await create(
	'Valentin',
	'Burgaud',
	'student@example.org',
	['user'],
	[promotion.id]
);
const teacher = await create('Marie', 'Dupont', 'teacher@example.org', ['teacher'], [promotion.id]);
const outsider = await create('Paul', 'Petit', 'outsider@example.org', ['user']);
assert.equal(typeof student.id, 'number');
assert.match(student.username, /^vburg\d{3}$/);
const old = await command('invitation', { id: student.id });
const invitation = await command('invitation', { id: student.id });
assert.equal(invitation.delivery, 'manual');
assert.ok(invitation.link.includes('/activate#token='));
assert.notEqual(old.token, invitation.token);
const teacherInvitation = await command('invitation', { id: teacher.id });
expectRedirect(await request('/logout', {}), '/');
assert.equal((await activation(old.token)).status, 400);
expectRedirect(await activation(invitation.token), '/login?notice=activated');
expectRedirect(await activation(teacherInvitation.token), '/login?notice=activated');
expectRedirect(await login(student.username), '/');
const studentSession = jar.get('sophikron_session_dev');
assert.equal((await request('/dashboard')).status, 403);
assert.equal((await request('/dashboard/data?resource=summary')).status, 403);
assert.equal(
	(await request('/dashboard/command', { command: 'createPromotion', data: {} }, origin, true))
		.status,
	403
);
const me = await (await request('/me')).text();
assert.ok(
	me.includes('Valentin') &&
		me.includes('BURGAUD') === false &&
		me.includes('Burgaud') &&
		me.includes('PTSI')
);
assert.equal(
	(
		await request('/me', {
			current_password: password,
			password: replacement,
			confirmation: 'mismatch'
		})
	).status,
	422
);
expectRedirect(
	await request('/me', {
		current_password: password,
		password: replacement,
		confirmation: replacement
	}),
	'/login?notice=password'
);
expectRedirect(await login(student.username, replacement), '/');
expectRedirect(await login('owner@example.org'), '/');
const adminSession = jar.get('sophikron_session_dev');
const renewed = await command('invitation', { id: student.id });
assert.equal(renewed.purpose, 'reset');
expectRedirect(await activation(renewed.token, replacement), '/login?notice=activated');
const archived = await command('archiveAccount', { id: student.id, data: { archived: true } });
assert.ok(archived.success);
assert.equal(
	(await request('/dashboard/command', { command: 'invitation', id: student.id }, origin, true))
		.status,
	409
);
const summary = await data('summary');
assert.equal(summary.total_accounts, 4);
assert.equal(summary.archived_accounts, 1);
const events = await data('events', { limit: '15' });
assert.ok(events.items.length > 0 && events.items.length <= 15);
assert.ok(
	events.items.every(
		(event, index) =>
			index === 0 ||
			new Date(events.items[index - 1].occurred_at) >= new Date(event.occurred_at)
	)
);
assert.equal((await data('search', { q: student.username }))[0].id, student.id);
jar.set('sophikron_session_dev', studentSession);
expectRedirect(await request('/me'), '/login');
expectRedirect(await login(teacher.username), '/');
const teacherSession = jar.get('sophikron_session_dev');
assert.equal((await request('/dashboard')).status, 200);
assert.equal((await data('users')).items[0].status, 'disabled');
assert.deepEqual(
	(await data('search', { q: 'burgo' })).map((item) => item.id),
	[student.id]
);
assert.equal((await request(`/dashboard/data?resource=user&id=${outsider.id}`)).status, 404);
assert.equal((await request('/dashboard/data?resource=summary')).status, 403);
assert.equal(
	(
		await request(
			'/dashboard/command',
			{ command: 'archiveAccount', id: student.id, data: { archived: false } },
			origin,
			true
		)
	).status,
	403
);
jar.set('sophikron_session_dev', adminSession);
const ownerProfile = await fetch(`${process.env.DB_TEST_API_URL}/api/v1/auth/me`, {
	headers: { cookie: `sophikron_session_dev=${adminSession}` }
});
const ownerId = (await ownerProfile.json()).id;
assert.equal(
	(
		await request(
			'/dashboard/command',
			{ command: 'archiveAccount', id: ownerId, data: { archived: true } },
			origin,
			true
		)
	).status,
	409
);

if (process.env.BFF_BROWSER_INTEGRATION === '1') {
	let profile = await data('profile', { id: student.id });
	for (let index = 0; index < 32; index++) {
		profile = await command('updateProfile', {
			id: student.id,
			data: {
				expected_version: profile.profile_version,
				orientation_project: `Parcours de vérification ${index}`
			}
		});
	}
	const { browserJourney } = await import('./browser.mjs');
	await browserJourney({ base, origin, adminSession, teacherSession, student, promotion });
}
console.log(
	'BFF HTTP journey passed: setup, personal profile, permissions, dashboard, promotions, scoped archived students, invitations and password resets.'
);
