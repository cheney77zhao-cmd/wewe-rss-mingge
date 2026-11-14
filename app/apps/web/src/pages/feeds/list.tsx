import { FC, useMemo } from 'react';
import {
  Table,
  TableHeader,
  TableColumn,
  TableBody,
  TableRow,
  TableCell,
  getKeyValue,
  Button,
  Spinner,
  Link,
} from '@nextui-org/react';
import { trpc } from '@web/utils/trpc';
import { articleUrl } from '@web/utils/article-url';
import { serverOriginUrl } from '@web/utils/env';
import dayjs from 'dayjs';
import { useParams } from 'react-router-dom';

const ArticleList: FC = () => {
  const { id } = useParams();

  const mpId = id || '';

  const { data, fetchNextPage, isLoading, isFetchingNextPage, hasNextPage } =
    trpc.article.list.useInfiniteQuery(
      {
        limit: 20,
        mpId: mpId,
      },
      {
        getNextPageParam: (lastPage) => lastPage.nextCursor,
      },
    );

  const items = useMemo(() => {
    const items = data
      ? data.pages.reduce((acc, page) => [...acc, ...page.items], [] as any[])
      : [];

    return items;
  }, [data]);

  return (
    <div className="article-list">
      <div className="mobile-articles">
        {isLoading ? <div className="mobile-list-status"><Spinner /></div> : items.length === 0 ? <div className="mobile-list-status">暂无文章</div> : null}
        {items.map((item) => <article className="mobile-article" key={item.id}>
          <a href={articleUrl(item.id, serverOriginUrl || '')} target="_blank" rel="noopener noreferrer">{item.title}<span aria-hidden="true"> ↗</span></a>
          <time dateTime={item.publishTime ? dayjs(item.publishTime * 1e3).toISOString() : undefined}>{item.publishTime ? dayjs(item.publishTime * 1e3).format('YYYY-MM-DD HH:mm') : '日期未知'}</time>
        </article>)}
        {hasNextPage && <Button className="mobile-load-more" variant="flat" isLoading={isFetchingNextPage} onPress={() => { fetchNextPage(); }}>加载更多</Button>}
      </div>
      <div className="desktop-articles">
      <Table
        classNames={{
          base: 'h-full',
          table: 'min-h-[420px]',
        }}
        aria-label="文章列表"
        bottomContent={
          hasNextPage && !isLoading ? (
            <div className="flex w-full justify-center">
              <Button
                isDisabled={isLoading}
                variant="flat"
                onPress={() => {
                  fetchNextPage();
                }}
              >
                {isLoading && <Spinner color="white" size="sm" />}
                加载更多
              </Button>
            </div>
          ) : null
        }
      >
        <TableHeader>
          <TableColumn key="title">标题</TableColumn>
          <TableColumn width={180} key="publishTime">
            发布时间
          </TableColumn>
        </TableHeader>
        <TableBody
          isLoading={isLoading}
          emptyContent={'暂无数据'}
          items={items || []}
          loadingContent={<Spinner />}
        >
          {(item) => (
            <TableRow key={item.id}>
              {(columnKey) => {
                let value = getKeyValue(item, columnKey);

                if (columnKey === 'publishTime') {
                  value = dayjs(value * 1e3).format('YYYY-MM-DD HH:mm:ss');
                  return <TableCell>{value}</TableCell>;
                }

                if (columnKey === 'title') {
                  return (
                    <TableCell>
                      <Link
                        className="visited:text-neutral-400"
                        isBlock
                        showAnchorIcon
                        color="foreground"
                        target="_blank"
                        href={articleUrl(item.id, serverOriginUrl || '')}
                      >
                        {value}
                      </Link>
                    </TableCell>
                  );
                }
                return <TableCell>{value}</TableCell>;
              }}
            </TableRow>
          )}
        </TableBody>
      </Table>
      </div>
    </div>
  );
};

export default ArticleList;
