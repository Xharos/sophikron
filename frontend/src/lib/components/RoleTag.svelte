<script lang="ts">
	import { resolve } from '$app/paths';
	import { roleLabels } from '#lib/roles';
	import Icon from './Icon.svelte';
	let {
		role,
		label,
		userId,
		historical = false
	}: {
		role: string | null;
		label?: string;
		userId?: number;
		historical?: boolean;
	} = $props();
	const roleLabel = $derived(role ? (roleLabels[role] ?? role) : 'Rôle non renseigné');
	const title = $derived(`${roleLabel}${historical ? ' au moment de l’action' : ''}`);
</script>

{#snippet content()}
	<Icon
		name={role === 'admin'
			? 'admin'
			: role === 'teacher'
				? 'teacher'
				: role === 'user'
					? 'student'
					: 'profile'}
		size={14}
	/>
	{label ?? roleLabel}
{/snippet}
{#if userId}
	<a
		class="role-badge"
		class:role-student={role === 'user'}
		class:role-teacher={role === 'teacher'}
		class:role-admin={role === 'admin'}
		href={resolve(`/dashboard/user?id=${userId}`)}
		title={`Voir la fiche · ${title}`}
	>
		{@render content()}
	</a>
{:else}
	<span
		class="role-badge"
		class:role-student={role === 'user'}
		class:role-teacher={role === 'teacher'}
		class:role-admin={role === 'admin'}
		{title}
	>
		{@render content()}
	</span>
{/if}

<style>
	.role-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.25rem 0.6rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 600;
		background: #edf1fa;
		color: #334155;
		vertical-align: middle;
		text-decoration: none;
		max-width: 100%;
		overflow-wrap: anywhere;
	}
	.role-student {
		background: #e8f1ff;
		color: #174ea6;
	}
	.role-teacher {
		background: #e7f3ec;
		color: #175c36;
	}
	.role-admin {
		background: #fdebec;
		color: #a51d2d;
	}
	a:hover {
		text-decoration: underline;
		box-shadow: inset 0 0 0 1px currentColor;
	}
	a:focus-visible {
		outline: 2px solid currentColor;
		outline-offset: 3px;
	}
</style>
