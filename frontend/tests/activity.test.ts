import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	eventDetails,
	eventSubjects,
	eventRoles,
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

test('downloads display course titles, including historical entries with no saved title', () => {
	assert.deepEqual(
		eventDetails(event('lesson.file_downloaded', { document_title: 'Exercices', file_id: 12 })),
		['Document : Exercices']
	);
	assert.deepEqual(eventDetails(event('lesson.file_downloaded', { file_id: 12 })), []);
});

test('recent scheduling and group actions expose useful bounded details', () => {
	assert.deepEqual(
		eventDetails(
			event('timetable.occurrence_deleted', {
				calendar_name: 'PT',
				title: 'Maths',
				occurrence: '2026-11-02',
				scope: 'future'
			})
		),
		['Calendrier : PT', 'Maths', 'Date : 2026-11-02', 'Cette occurrence et les suivantes']
	);
	assert.deepEqual(
		eventDetails(
			event('promotion.custom_group_created', { group_name: 'Allemand', student_count: 10 })
		),
		['Groupe : Allemand', '10 élèves']
	);
});

test('partition activity distinguishes independent group families without pupil identities', () => {
	assert.deepEqual(eventDetails(event('promotion.groups_saved', { kind: 'halves' })), [
		'Demi-groupes'
	]);
	assert.deepEqual(eventDetails(event('promotion.groups_deleted', { kind: 'kholles' })), [
		'Groupes de khôlle'
	]);
	assert.deepEqual(eventDetails(event('promotion.groups_saved', { kind: '<script>' })), []);
});

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
	assert.equal(highestRole(['kholleur']), 'kholleur');
	assert.deepEqual(eventRoles(['kholleur', 'forged']), ['kholleur']);
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

test('course events expose link tokens and useful scheduling facts without body content', () => {
	assert.deepEqual(
		messageParts('{actor} a modifié {lesson}.').map((part) => part.kind),
		['actor', 'text', 'lesson', 'text']
	);
	const details = eventDetails(
		event('lesson.element_updated', {
			element_kind: 'text',
			element_title: 'Introduction',
			changed_fields: ['body', 'schedule_mode'],
			previous_period: { mode: 'inherit', starts_on: null, ends_on: null },
			period: { mode: 'from', starts_on: '2026-09-01', ends_on: null },
			body: 'PRIVATE-CONTENT'
		})
	);
	assert.ok(details.includes('Texte : Introduction'));
	assert.ok(details.includes('Champs modifiés : Contenu, Règle de disponibilité'));
	assert.ok(details.some((detail) => detail.includes('2026-09-01')));
	assert.ok(!details.join(' ').includes('PRIVATE-CONTENT'));
});

test('assignment deltas validate historical subject tags and retain automatic causes', () => {
	const matter = { id: 12, name: 'Mathématiques', icon: 'calculator', color: '#123456' };
	assert.deepEqual(eventSubjects([matter]), [matter]);
	assert.deepEqual(
		eventSubjects([
			null,
			{ ...matter, color: 'red' },
			{ ...matter, icon: '<svg>' },
			{ ...matter, id: -1 }
		]),
		[]
	);
	assert.deepEqual(eventDetails(event('user.subjects_updated', { reason: 'account_archived' })), [
		'Retrait automatique lors de l’archivage du compte.'
	]);
	for (const type of ['user.subjects_updated', 'subject.saved', 'site.updated'])
		assert.deepEqual(eventDetails(event(type, {})), []);
});
test('site and subject details identify saved facts without copying text bodies', () => {
	const site = eventDetails(
		event('site.updated', {
			changed_fields: ['name', 'home_text', 'text_color'],
			previous_name: 'Avant',
			name: 'Après',
			home_text: 'PRIVATE-BODY'
		})
	);
	assert.ok(site.includes('Nom du site : Avant → Après'));
	assert.ok(site.some((line) => line.includes('Texte d’accueil, Couleur du texte')));
	assert.ok(!site.join(' ').includes('PRIVATE-BODY'));
	assert.ok(
		eventDetails(
			event('subject.saved', { action: 'updated', changed_fields: ['name', 'color'] })
		).includes('Champs modifiés : Nom, Couleur')
	);
});

test('promotion account actions identify their cause and effective login changes', () => {
	assert.deepEqual(eventDetails(event('promotion.member_removed', { reason: 'role_removed' })), [
		'Retrait automatique : aucun rôle Élève, Enseignant ou Khôlleur conservé.'
	]);
	assert.deepEqual(eventDetails(event('promotion.member_removed', {})), []);
	assert.deepEqual(eventDetails(event('promotion.member_removed', { reason: 'manual' })), []);
	assert.deepEqual(
		eventDetails(
			event('user.archived', { promotion_id: 3, promotion: { year: 2026, identifier: 'PCSI' } })
		),
		['Via la promotion 2026 · PCSI']
	);
	assert.deepEqual(eventDetails(event('user.archived', {})), []);
	assert.deepEqual(
		eventDetails(event('promotion.reactivated', { student_blocks: 5, accounts_changed: 3 })),
		['5 blocages élèves levés', '3 comptes réactivés']
	);
});

test('activity counts use singular only for one, including adjective agreements', () => {
	for (const count of [0, 1, 2]) {
		const suffix = count === 1 ? '' : 's';
		for (const [action, block, account] of [
			['archived', 'ajouté', 'désactivé'],
			['reactivated', 'levé', 'réactivé']
		]) {
			assert.deepEqual(
				eventDetails(
					event(`promotion.${action}`, { student_blocks: count, accounts_changed: count })
				),
				[
					`${count} blocage${suffix} élèves ${block}${suffix}`,
					`${count} compte${suffix} ${account}${suffix}`
				]
			);
		}
		assert.ok(
			eventDetails(event('lesson.element_deleted', { removed_count: count })).includes(
				`${count} élément${suffix} supprimé${suffix}, enfants compris`
			)
		);
		if (count > 0) {
			assert.ok(
				eventDetails(
					event('subject.archived', { action: 'archived', removed_assignments: count })
				).includes(`${count} affectation${suffix} retirée${suffix}`)
			);
		}
	}
});
