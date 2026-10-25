import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	eventDetails,
	highestRole,
	messageParts,
	roleTransitionLabel
} from '../src/lib/activity.ts';
import type { ActivityEvent } from '../src/lib/types.ts';

function event(event_type: string, data: Record<string, unknown>): ActivityEvent {
	return {
		id: 1,
		event_type,
		data,
		occurred_at: '2026-10-25T12:00:00Z',
		actor_user_id: 1,
		subject_user_id: 2,
		actor_role: 'admin',
		subject_role: 'user',
		actor_profile_available: true,
		subject_profile_available: true,
		actor_label: 'Val Burgaud',
		subject_label: 'Marie Tidj',
		resource_type: null,
		resource_id: null,
		promotion_snapshot: null,
		resource_label: null
	};
}

test('messages preserve participant positions and leave unknown markup as literal text', () => {
	assert.deepEqual(
		messageParts('{actor} a ajouté {subject} à {promotion}.').map((part) => part.kind),
		['actor', 'text', 'subject', 'text', 'promotion', 'text']
	);
	assert.deepEqual(messageParts('<b>{password}</b>'), [
		{ kind: 'text', text: '<b>{password}</b>' }
	]);
});

test('combined role changes stay explicit even when their highest role remains administrator', () => {
	assert.equal(highestRole(['teacher', 'admin']), 'admin');
	assert.equal(highestRole([]), null);
	assert.equal(
		roleTransitionLabel('Marie', ['teacher', 'admin']),
		'Marie · Enseignant + Administrateur'
	);
	assert.notEqual(
		roleTransitionLabel('Marie', ['admin']),
		roleTransitionLabel('Marie', ['teacher', 'admin'])
	);
});

test('profile messages list changed fields without exposing copied personal values', () => {
	const details = eventDetails(
		event('user.profile_updated', { changed_fields: ['phone', 'email'], phone: 'private-contact' })
	);
	assert.deepEqual(details, ['Champs modifiés : Téléphone, Email']);
	assert.ok(!details.join(' ').includes('private-contact'));
	assert.deepEqual(
		eventDetails(
			event('promotion.updated', {
				changed_fields: ['identifier'],
				previous: { identifier: 'PTSI' },
				current: { identifier: 'PSI' }
			})
		),
		['Identifiant : PTSI → PSI']
	);
	assert.deepEqual(
		eventDetails(event('invitation.issued', { purpose: 'reset', delivery: 'manual' })),
		['Invitation à réinitialiser le mot de passe', 'Lien à remettre manuellement']
	);
});
