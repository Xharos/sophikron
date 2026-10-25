import { roleLabels } from './roles.ts';
import type { ActivityEvent } from './types';

export type MessagePart = {
	kind: 'text' | 'actor' | 'subject' | 'promotion' | 'roles';
	text: string;
};

/** Templates contain only literal text and a small vocabulary of rendered Svelte tags. */
export function messageParts(message: string): MessagePart[] {
	return message
		.split(/(\{(?:actor|subject|promotion|roles)\})/g)
		.filter(Boolean)
		.map((text) => {
			const token = /^\{(actor|subject|promotion|roles)\}$/.exec(text);
			return { kind: token ? (token[1] as MessagePart['kind']) : 'text', text };
		});
}

/** Narrow event metadata without trusting arbitrary values as role codes. */
export function eventRoles(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter(
				(role): role is string =>
					typeof role === 'string' && ['user', 'teacher', 'admin'].includes(role)
			)
		: [];
}

export function highestRole(roles: string[]): string | null {
	return ['admin', 'teacher', 'user'].find((role) => roles.includes(role)) ?? null;
}

/** Retain combined grants in before/after labels even when the highest role stays admin. */
export function roleTransitionLabel(name: string, roles: string[]): string {
	return `${name} · ${roles.map((role) => roleLabels[role] ?? role).join(' + ') || 'Rôle non renseigné'}`;
}

const fieldLabels: Record<string, string> = {
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
	color: 'Couleur'
};

function objectValue(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

/** Explain recorded facts without copying private profile values or invitation secrets. */
export function eventDetails(event: ActivityEvent): string[] {
	const data = event.data;
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
