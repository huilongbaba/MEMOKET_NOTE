/**
 * 局部图：主题页 / 实体页上的「这个东西周围有什么」。Capacities 用「每个节点的局部图」
 * 缓解全图看不清的问题——全图是 126 个主题 + 1220 个实体，局部图只画这一个及其邻居。
 * 直接复用 KnowledgeGraph，节点少于 150 时它自己就会摊开、标签常显。
 */
import type { EntityNode, TopicEntityLink, TopicNode } from '../../api'
import KnowledgeGraph from '../KnowledgeGraph'
import type { KbActions } from './KbBits'

export default function LocalGraph({ topics, entities, links, actions, height = 320 }: {
  topics: TopicNode[]; entities: EntityNode[]; links: TopicEntityLink[]; actions: KbActions; height?: number
}) {
  if (topics.length + entities.length < 2) return null
  return (
    <div className="local-graph">
      <KnowledgeGraph
        topics={topics} entities={entities} links={links} height={height}
        onSelect={(kind, code) => actions.onOpen((kind === 'topic' ? 'kb:topic:' : 'kb:entity:') + code)}
      />
    </div>
  )
}
