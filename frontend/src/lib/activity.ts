import { roleLabels } from './roles.ts';
import { lessonIcons, lessonDate } from './lessons.ts';
import type { Subject } from './site.ts';
import type { ActivityEvent } from './types';

export type MessagePart = {
	kind: 'text' | 'actor' | 'subject' | 'promotion' | 'roles' | 'lesson';
	text: string;
};

/** Templates contain only literal text and a small vocabulary of rendered Svelte tags. */
export function messageParts(message: string): MessagePart[] {
	return message
		.split(/(\{(?:actor|subject|promotion|roles|lesson)\})/g)
		.filter(Boolean)
		.map((text) => {
			const token = /^\{(actor|subject|promotion|roles|lesson)\}$/.exec(text);
			return { kind: token ? (token[1] as MessagePart['kind']) : 'text', text };
		});
}

/** Narrow event metadata without trusting arbitrary values as role codes. */
export function eventRoles(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter(
				(role): role is string =>
					typeof role === 'string' && ['user', 'kholleur', 'teacher', 'admin'].includes(role)
			)
		: [];
}

export function highestRole(roles: string[]): string | null {
	return ['admin', 'teacher', 'kholleur', 'user'].find((role) => roles.includes(role)) ?? null;
}

/** Retain combined grants in before/after labels even when the highest role stays admin. */
export function roleTransitionLabel(name: string, roles: string[]): string {
	return `${name} · ${roles.map((role) => roleLabels[role] ?? role).join(' + ') || 'Rôle non renseigné'}`;
}

const fieldLabels: Record<string, string> = {
	audience: 'Visibilité',
	table_structure: 'Lignes et colonnes du tableau',
	first_name: 'Prénom',
	last_name: 'Nom',
	email: 'Email',
	birth_date: 'Date de naissance',
	city: 'Ville',
	postal_code: 'Code postal',
	commune_code: 'Commune',
	previous_school: 'Établissement précédent',
	baccalaureate: 'Baccalauréat',
	orientation_project: 'Projet d’orientation',
	phone: 'Téléphone',
	reference_adult: 'Adulte référent',
	identifier: 'Identifiant',
	year: 'Année',
	color: 'Couleur',
	title: 'Titre',
	description: 'Description',
	icon: 'Icône',
	body: 'Contenu',
	schedule_mode: 'Règle de disponibilité',
	starts_on: 'Date de début',
	ends_on: 'Date de fin',
	name: 'Nom',
	home_text: 'Texte d’accueil',
	text_color: 'Couleur du texte',
	holiday_color: 'Couleur des vacances',
	kind: 'Type',
	timeline_ids: 'Timelines concernées',
	responsible_id: 'Responsable principal',
	subject_id: 'Matière'
};

function objectValue(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

export type ActivitySubject = Pick<Subject, 'id' | 'name' | 'icon' | 'color'>;

/** Validate historical subject tags before using their icon or color in the UI. */
export function eventSubjects(value: unknown): ActivitySubject[] {
	if (!Array.isArray(value)) return [];
	return value.filter((item): item is ActivitySubject => {
		const subject = objectValue(item);
		return (
			Number.isSafeInteger(subject.id) &&
			Number(subject.id) > 0 &&
			typeof subject.name === 'string' &&
			subject.name.length > 0 &&
			subject.name.length <= 100 &&
			lessonIcons.some((icon) => icon.value === subject.icon) &&
			typeof subject.color === 'string' &&
			/^#[0-9a-f]{6}$/i.test(subject.color)
		);
	});
}

/** Explain recorded facts without copying private profile values or invitation secrets. */
export function eventDetails(event: ActivityEvent): string[] {
	const data = event.data;
	if (event.event_type === 'promotion.member_removed' && data.reason === 'role_removed')
		return ['Retrait automatique : aucun rôle Élève, Enseignant ou Khôlleur conservé.'];
	if (['user.archived', 'user.reactivated'].includes(event.event_type)) {
		const promotion = data.promotion;
		if (
			typeof data.promotion_id !== 'number' ||
			!promotion ||
			typeof promotion !== 'object' ||
			!('identifier' in promotion) ||
			typeof promotion.identifier !== 'string' ||
			!('year' in promotion) ||
			typeof promotion.year !== 'number'
		)
			return [];
		return ['Via la promotion ' + promotion.year + ' · ' + promotion.identifier];
	}
	if (['promotion.archived', 'promotion.reactivated'].includes(event.event_type)) {
		if (typeof data.student_blocks !== 'number' || typeof data.accounts_changed !== 'number')
			return [];
		return [
			data.student_blocks +
				(event.event_type === 'promotion.archived'
					? ` blocage${data.student_blocks === 1 ? '' : 's'} élèves ajouté${data.student_blocks === 1 ? '' : 's'}`
					: ` blocage${data.student_blocks === 1 ? '' : 's'} élèves levé${data.student_blocks === 1 ? '' : 's'}`),
			data.accounts_changed +
				` compte${data.accounts_changed === 1 ? '' : 's'} ` +
				(event.event_type === 'promotion.archived' ? 'désactivé' : 'réactivé') +
				(data.accounts_changed === 1 ? '' : 's')
		];
	}
	if (event.event_type === 'user.subjects_updated') {
		const reasons: Record<string, string> = {
			role_removed: 'Retrait automatique : aucun rôle Enseignant ou Khôlleur conservé.',
			account_archived: 'Retrait automatique lors de l’archivage du compte.',
			subject_archived: 'Retrait automatique lors de l’archivage de la matière.'
		};
		return typeof data.reason === 'string' && Object.hasOwn(reasons, data.reason)
			? [reasons[data.reason]]
			: [];
	}
	if (event.event_type === 'subject.saved' || event.event_type === 'subject.archived') {
		if (!['created', 'updated', 'archived'].includes(String(data.action))) return [];
		const details = [
			data.action === 'created'
				? 'Création de la matière'
				: data.action === 'updated'
					? 'Modification de la matière'
					: 'Archivage de la matière'
		];
		if (Array.isArray(data.changed_fields) && data.changed_fields.length)
			details.push(
				'Champs modifiés : ' +
					data.changed_fields
						.filter((field): field is string => typeof field === 'string')
						.map((field) => fieldLabels[field] ?? field)
						.join(', ')
			);
		if (typeof data.removed_assignments === 'number' && data.removed_assignments > 0)
			details.push(
				`${data.removed_assignments} affectation${data.removed_assignments === 1 ? '' : 's'} retirée${data.removed_assignments === 1 ? '' : 's'}`
			);
		return details;
	}
	if (event.event_type === 'site.updated') {
		const fields = Array.isArray(data.changed_fields)
			? data.changed_fields.filter((field): field is string => typeof field === 'string')
			: [];
		const details: string[] = [];
		if (
			fields.includes('name') &&
			typeof data.previous_name === 'string' &&
			typeof data.name === 'string'
		)
			details.push('Nom du site : ' + data.previous_name + ' → ' + data.name);
		const remaining = fields.filter((field) => field !== 'name' || !details.length);
		if (remaining.length)
			details.push(
				'Champs modifiés : ' + remaining.map((field) => fieldLabels[field] ?? field).join(', ')
			);
		return details;
	}
	if (event.event_type === 'calendar.saved' || event.event_type === 'calendar.deleted') {
		if (typeof data.name !== 'string') return [];
		const details = [(data.entry_type === 'timeline' ? 'Timeline : ' : 'Événement : ') + data.name];
		const actions: Record<string, string> = {
			created: 'Création',
			updated: 'Modification',
			deleted: 'Suppression'
		};
		if (typeof data.action === 'string' && Object.hasOwn(actions, data.action))
			details.push('Action : ' + actions[data.action]);
		if (typeof data.starts_on === 'string' && typeof data.ends_on === 'string')
			details.push('Dates : ' + lessonDate(data.starts_on) + ' → ' + lessonDate(data.ends_on));
		const kinds: Record<string, string> = {
			holiday: 'Vacances',
			oral: 'Oraux',
			written: 'Écrits',
			school: 'École',
			other: 'Autre'
		};
		if (typeof data.kind === 'string' && Object.hasOwn(kinds, data.kind))
			details.push('Type : ' + kinds[data.kind]);
		if (typeof data.timeline_count === 'number')
			details.push(
				`${data.timeline_count} timeline${data.timeline_count === 1 ? '' : 's'} concernée${data.timeline_count === 1 ? '' : 's'}`
			);
		if (Array.isArray(data.changed_fields) && data.changed_fields.length)
			details.push(
				'Champs modifiés : ' +
					data.changed_fields
						.filter((field): field is string => typeof field === 'string')
						.map((field) => fieldLabels[field] ?? field)
						.join(', ')
			);
		if (typeof data.deleted_events === 'number' && data.deleted_events > 0)
			details.push(
				`${data.deleted_events} événement${data.deleted_events === 1 ? '' : 's'} exclusif${data.deleted_events === 1 ? '' : 's'} supprimé${data.deleted_events === 1 ? '' : 's'}`
			);
		if (typeof data.retained_events === 'number' && data.retained_events > 0)
			details.push(
				`${data.retained_events} événement${data.retained_events === 1 ? '' : 's'} partagé${data.retained_events === 1 ? '' : 's'} conservé${data.retained_events === 1 ? '' : 's'}`
			);
		return details;
	}
	if (event.event_type.startsWith('lesson.')) {
		const details: string[] = [];
		const kind =
			typeof data.element_kind === 'string'
				? (
						{
							section: 'Section',
							subsection: 'Sous-section',
							text: 'Texte',
							youtube: 'Vidéo YouTube',
							file: 'Document',
							table: 'Tableau de ressources'
						} as Record<string, string>
					)[data.element_kind]
				: null;
		if (kind)
			details.push(
				`${kind}${typeof data.element_title === 'string' && data.element_title ? ` : ${data.element_title}` : ''}`
			);
		if (Array.isArray(data.changed_fields) && data.changed_fields.length)
			details.push(
				`Champs modifiés : ${data.changed_fields
					.filter((value): value is string => typeof value === 'string')
					.map((field) => fieldLabels[field] ?? field)
					.join(', ')}`
			);
		if (typeof data.removed_count === 'number')
			details.push(
				`${data.removed_count} élément${data.removed_count === 1 ? '' : 's'} supprimé${data.removed_count === 1 ? '' : 's'}, enfants compris`
			);
		if (data.direction === 'up' || data.direction === 'down')
			details.push(data.direction === 'up' ? 'Déplacé vers le haut' : 'Déplacé vers le bas');
		const promotion = objectValue(data.promotion);
		if (typeof promotion.identifier === 'string')
			details.push(`Promotion : ${promotion.identifier} · ${promotion.year}`);
		for (const [key, label] of [
			['previous_period', 'Période précédente'],
			['period', 'Période']
		] as const) {
			const period = objectValue(data[key]);
			if (period.mode === 'inherit') details.push(`${label} : toute l’année / héritée du parent`);
			else if (typeof period.starts_on === 'string')
				details.push(
					`${label} : ${period.starts_on}${typeof period.ends_on === 'string' ? ` → ${period.ends_on}` : ' et suivantes'}`
				);
		}
		return details;
	}
	if (event.event_type === 'user.created')
		return [
			`Rôles attribués : ${
				eventRoles(data.roles)
					.map((role) => roleLabels[role])
					.join(' + ') || 'non renseignés'
			}`
		];
	if (event.event_type === 'invitation.issued')
		return [
			data.purpose === 'reset'
				? 'Invitation à réinitialiser le mot de passe'
				: 'Invitation à activer le compte',
			data.delivery === 'manual' ? 'Lien à remettre manuellement' : 'Envoi par email'
		];
	const fields = Array.isArray(data.changed_fields)
		? data.changed_fields.filter((field): field is string => typeof field === 'string')
		: [];
	if (event.event_type === 'user.profile_updated')
		return fields.length
			? [`Champs modifiés : ${fields.map((field) => fieldLabels[field] ?? field).join(', ')}`]
			: [];
	if (event.event_type === 'promotion.updated') {
		const previous = objectValue(data.previous),
			current = objectValue(data.current);
		return fields.map(
			(field) =>
				`${fieldLabels[field] ?? field} : ${String(previous[field] ?? '—')} → ${String(current[field] ?? '—')}`
		);
	}
	return [];
}
