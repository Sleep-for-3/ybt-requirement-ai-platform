"use client";

import Link, { LinkProps } from "next/link";
import { usePathname } from "next/navigation";
import { AnchorHTMLAttributes, useEffect, useState } from "react";

import { detailHrefWithReturnTo } from "@/lib/navigation-contract.mjs";

type StatefulLinkProps = LinkProps & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, keyof LinkProps>;

export function StatefulLink({ href, ...props }: StatefulLinkProps) {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  useEffect(() => { setQuery(window.location.search.slice(1)); }, [pathname]);
  const resolvedHref = typeof href === "string"
    ? detailHrefWithReturnTo(href, pathname, query)
    : href;

  return <Link href={resolvedHref} {...props} />;
}
