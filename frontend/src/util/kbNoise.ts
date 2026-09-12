/** 知识库里的「伪实体」：录音转写的说话人标签（Speaker A / speaker_c / 说话人 1…）。
 *  抽取会把它们当实体，而且事实数最多——实体索引、首页 top、主题页局部图、主题地图
 *  都要认得出它们。一处定义，四处用。 */
export const SPEAKER_TAG = /^(speaker[\s_-]?[a-z0-9]{1,2}|说话人\s?[a-z0-9]{1,2}|发言人\s?[a-z0-9]{1,2})$/i

export function isSpeakerTag(name: string): boolean {
  return SPEAKER_TAG.test((name ?? '').trim())
}
