<script lang="ts">
	import type { Promotion } from '#lib/types';
	import { statusLabels } from '#lib/dashboard';
	import RoleBadges from './RoleBadges.svelte';
	import PromotionTag from './PromotionTag.svelte';
	let {
		user
	}: {
		user: {
			first_name?: string | null;
			last_name?: string | null;
			label?: string;
			username?: string;
			status?: string;
			roles?: string[];
			role?: string | null;
			promotions?: Promotion[];
		};
	} = $props();
	const name = $derived(user.label ?? `${user.first_name ?? ''} ${user.last_name ?? ''}`.trim());
	const initials = $derived(
		name
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part[0])
			.join('')
	);
	const roles = $derived(user.roles ?? (user.role ? [user.role] : []));
</script>

<span class="picker-identity">
	<span class="avatar" aria-hidden="true">{initials}</span>
	<span class="picker-identity-body">
		<span class="picker-identity-heading"
			><strong>{name}</strong>
			{#if user.status}<span
					class="account-status"
					class:archived={user.status === 'disabled'}
					class:pending={user.status === 'pending_activation'}
					>{statusLabels[user.status] ?? user.status}</span
				>{/if}
		</span>
		{#if user.username}<span class="muted text-small picker-username">@{user.username}</span>{/if}
		{#if roles.length || user.promotions?.length}<span class="picker-identity-tags">
				{#if roles.length}<RoleBadges {roles} />{/if}
				{#each user.promotions ?? [] as promotion (promotion.id)}<PromotionTag {promotion} />{/each}
			</span>{/if}
	</span>
</span>

<style>
	.picker-identity {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex: 1;
		min-width: 0;
	}
	.picker-identity-body {
		display: grid;
		gap: 0.3rem;
		min-width: 0;
		flex: 1;
	}
	.picker-identity-heading,
	.picker-identity-tags {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem 0.5rem;
	}
	strong,
	.picker-username {
		overflow-wrap: anywhere;
	}
	strong {
		color: var(--color-ink);
		font-size: 0.87rem;
	}
	.picker-username {
		font-size: 0.75rem;
	}
	.picker-identity-tags :global(.promotion-tag),
	.picker-identity-tags :global(.role-badge) {
		font-size: 0.7rem;
		padding: 0.2rem 0.4rem;
	}
	@media (max-width: 400px) {
		.avatar {
			width: 30px;
			height: 30px;
			border-radius: 9px;
		}
		.picker-identity {
			gap: 0.5rem;
		}
	}
</style>
