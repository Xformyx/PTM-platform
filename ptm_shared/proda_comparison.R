args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 4) stop("input/design/output/pinned version required")
if (!requireNamespace("proDA",quietly=TRUE)) stop("proDA unavailable")
if (as.character(utils::packageVersion("proDA")) != args[4]) stop("proDA version mismatch")
data <- as.matrix(read.delim(args[1],row.names=1,check.names=FALSE,na.strings="NA"))
samples <- read.delim(args[2],stringsAsFactors=FALSE)
stopifnot(identical(colnames(data),samples$sample))
groups <- factor(samples$condition,levels=sort(unique(samples$condition)))
design <- model.matrix(~0+groups)
colnames(design) <- levels(groups)
fit <- proDA::proDA(data,design=design,data_is_log_transformed=TRUE)
records <- lapply(setdiff(levels(groups),"C0"),function(condition) {
  result <- proDA::test_diff(fit,contrast=paste0(condition,"-C0"),pval_adjust_method="BH")
  result$condition <- condition
  result
})
write.table(do.call(rbind,records),args[3],sep="\t",quote=FALSE,row.names=FALSE,na="NA")
