// Previously cached reader modules still import this interface to load a chapter.
export function createReadAloud() {
  return { setChapter() {}, reset() {}, refreshKorean() {} };
}
